"""ScamWatch: URL checking and reporting.

Security design:
  * The submitted URL is NEVER fetched by this server. Providers receive it only as DATA (a lookup against a
    fixed provider host, or offline string analysis), so there is no server-side-request-forgery surface and
    no open proxy.
  * "No known threat detected" never means "safe". Every response says so.
  * Provider credentials stay on the backend and never appear in logs or error messages.
"""
import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import ScamReport, utcnow
from .audit import record_audit
from .investigation_service import ensure_case

DISCLAIMER = ("No known threat detected does not mean a website is safe. Threat databases only list sites that "
              "have already been found and reported. Be careful with links you did not expect.")
VERDICT_RANK = {"inconclusive": 0, "no_known_threat": 1, "suspicious": 2, "malicious": 3}
REVIEW_STATUSES = ("pending", "reviewed_malicious", "reviewed_benign", "dismissed")
TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|mc_eid|igshid)$", re.IGNORECASE)
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "cutt.ly", "rb.gy", "shorturl.at"}
RISKY_TLDS = {"zip", "mov", "top", "xyz", "tk", "ml", "ga", "cf", "gq", "click", "country", "kim", "work", "support",
              "icu", "buzz", "rest", "cyou"}
LURE_WORDS = ("login", "signin", "verify", "secure", "account", "update", "wallet", "gift", "prize", "winner", "claim",
              "voucher", "reward", "refund", "suspended", "unlock", "bonus")


class InvalidUrl(ValueError):
    """The text is not an acceptable http(s) URL. The message is safe to show to the user."""


def normalize_url(raw: str) -> tuple[str, str, list[str]]:
    """Return (normalized_url, domain, notes). Raises InvalidUrl. Performs no network access."""
    text = (raw or "").strip()
    if not text:
        raise InvalidUrl("Enter a web address to check.")
    if len(text) > 2048:
        raise InvalidUrl("That web address is too long.")
    if re.search(r"[\s\x00-\x1f\x7f]", text):
        raise InvalidUrl("A web address cannot contain spaces or control characters.")
    if "://" not in text:
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", text) and not re.match(r"^[^/]*:\d+(/|$)", text):
            raise InvalidUrl("Only http and https web addresses can be checked.")
        text = "http://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise InvalidUrl("That does not look like a valid web address.")
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidUrl("Only http and https web addresses can be checked.")
    host = (parts.hostname or "").strip(".").lower()
    if not host:
        raise InvalidUrl("That web address has no website name.")
    notes: list[str] = []
    if parts.username or parts.password:
        notes.append("contains_credentials_in_url")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise InvalidUrl("Private, local and reserved network addresses are not accepted.")
        notes.append("ip_address_host")
        domain = str(ip)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise InvalidUrl("That website name is not valid.")
        if ascii_host != host:
            notes.append("internationalised_domain")
        host = ascii_host
        if "." not in host or host.endswith((".local", ".internal", ".localhost", ".lan")) or host == "localhost":
            raise InvalidUrl("Enter a full public website name such as example.com.")
        if not re.match(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$", host):
            raise InvalidUrl("That website name is not valid.")
        domain = host
    default = {"http": 80, "https": 443}[parts.scheme.lower()]
    netloc = host if (port is None or port == default) else f"{host}:{port}"
    if ":" in host:                                   # IPv6 literal
        netloc = f"[{host}]" + ("" if port in (None, default) else f":{port}")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not TRACKING_PARAMS.match(k)))
    path = parts.path or "/"
    normalized = f"{parts.scheme.lower()}://{netloc}{path}" + (f"?{query}" if query else "")
    return normalized, domain, notes


def url_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode()).hexdigest()


# ---------------------------------------------------------------- providers
@dataclass
class ProviderResult:
    provider: str
    status: str                  # ok | error | skipped
    verdict: str                 # malicious | suspicious | no_known_threat | inconclusive
    detail: str
    source: str                  # where the answer came from
    simulated: bool = False
    signals: list[str] = field(default_factory=list)


class HeuristicProvider:
    """Offline string analysis. It can raise suspicion; it can never prove a site is safe or malicious."""
    name = "heuristic"

    def __init__(self, brands: list[str], official_domains: list[str]):
        self.brands, self.official = brands, official_domains

    def check(self, normalized: str, domain: str, notes: list[str]) -> ProviderResult:
        signals, score = [], 0
        if "ip_address_host" in notes:
            signals.append("Uses a raw IP address instead of a website name"); score += 2
        if "contains_credentials_in_url" in notes:
            signals.append("Contains a username or password before the host (a common disguise)"); score += 3
        if "internationalised_domain" in notes or "xn--" in domain:
            signals.append("Uses look-alike (international) characters in the domain"); score += 2
        labels = domain.split(".")
        if len(labels) >= 5:
            signals.append("Has an unusually long chain of subdomains"); score += 1
        if labels[-1] in RISKY_TLDS:
            signals.append(f"Ends in '.{labels[-1]}', a domain ending often abused by scammers"); score += 1
        if domain in SHORTENERS:
            signals.append("Is a link shortener, which hides the real destination"); score += 2
        lowered = normalized.lower()
        lures = [w for w in LURE_WORDS if w in lowered]
        if lures:
            signals.append("Contains words often used in lures: " + ", ".join(lures[:4])); score += min(len(lures), 2)
        registrable = ".".join(labels[-3:]) if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "gov") else ".".join(labels[-2:])
        for brand in self.brands:
            if brand in domain and registrable not in self.official and domain not in self.official:
                signals.append(f"Mentions the brand '{brand}' but is not one of its listed official domains"); score += 3
        if domain.count("-") >= 3:
            signals.append("Has many hyphens in the domain"); score += 1
        verdict = "suspicious" if score >= 3 else "inconclusive"
        detail = ("Offline heuristic checks only (not a threat-intelligence feed). " +
                  ("Warning signs found." if signals else "No warning signs found, which does not mean the site is safe."))
        return ProviderResult("heuristic", "ok", verdict, detail, "local rules", signals=signals)


class SafeBrowsingProvider:
    """Google Safe Browsing lookup. Optional: needs SAFE_BROWSING_API_KEY. Sends the URL to Google.

    The request goes to ONE fixed host. The key lives in the query string, so errors are reported without
    the URL and httpx request logging is disabled at WARNING level.
    """
    name = "safebrowsing"
    ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=5.0, follow_redirects=False)

    def check(self, normalized: str, domain: str, notes: list[str]) -> ProviderResult:
        if not self.api_key:
            return ProviderResult(self.name, "skipped", "inconclusive", "Not configured (no API key).", "Google Safe Browsing")
        body = {"client": {"clientId": "fraudguard-demo", "clientVersion": "1.0"},
                "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                                               "POTENTIALLY_HARMFUL_APPLICATION"],
                               "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                               "threatEntries": [{"url": normalized}]}}
        try:
            r = self.client.post(self.ENDPOINT, params={"key": self.api_key}, json=body)
        except httpx.TimeoutException:
            return ProviderResult(self.name, "error", "inconclusive", "The provider timed out.", "Google Safe Browsing")
        except httpx.HTTPError as exc:
            return ProviderResult(self.name, "error", "inconclusive",
                                  f"The provider could not be reached ({type(exc).__name__}).", "Google Safe Browsing")
        if r.status_code != 200:
            return ProviderResult(self.name, "error", "inconclusive", f"The provider returned HTTP {r.status_code}.",
                                  "Google Safe Browsing")
        try:
            matches = r.json().get("matches", [])
        except ValueError:
            return ProviderResult(self.name, "error", "inconclusive", "The provider sent an unreadable answer.",
                                  "Google Safe Browsing")
        if matches:
            kinds = sorted({m.get("threatType", "UNKNOWN") for m in matches})
            return ProviderResult(self.name, "ok", "malicious", "Listed by Google Safe Browsing: " + ", ".join(kinds),
                                  "Google Safe Browsing", signals=kinds)
        return ProviderResult(self.name, "ok", "no_known_threat", "Not on Google Safe Browsing's lists right now.",
                              "Google Safe Browsing")


class MockProvider:
    """Deterministic provider for automated tests and demos. Always labelled SIMULATED."""
    name = "mock"

    def __init__(self, verdicts: dict[str, str] | None = None, fail: bool = False):
        self.verdicts, self.fail = verdicts or {}, fail

    def check(self, normalized: str, domain: str, notes: list[str]) -> ProviderResult:
        if self.fail:
            return ProviderResult("mock", "error", "inconclusive", "Simulated provider failure.", "mock", simulated=True)
        verdict = self.verdicts.get(domain, "no_known_threat")
        return ProviderResult("mock", "ok", verdict, f"SIMULATED result for demonstration: {verdict}.", "mock",
                              simulated=True)


def build_providers(s: Settings) -> list:
    out = []
    for name in s.provider_list:
        if name == "heuristic":
            out.append(HeuristicProvider(s.brand_list, s.official_domain_list))
        elif name == "safebrowsing":
            out.append(SafeBrowsingProvider(s.safe_browsing_api_key))
        # unknown names are ignored on purpose; /settings/integrations shows what is really active
    return out


def provider_status(s: Settings) -> list[dict]:
    rows = []
    for name in s.provider_list:
        if name == "heuristic":
            rows.append({"name": "heuristic", "configured": True, "kind": "offline rules",
                         "live_tested": False, "note": "Offline heuristic; not a threat-intelligence feed."})
        elif name == "safebrowsing":
            rows.append({"name": "safebrowsing", "configured": bool(s.safe_browsing_api_key), "kind": "external lookup",
                         "live_tested": False,
                         "note": "Needs SAFE_BROWSING_API_KEY. Live calls have not been verified in this project."})
        else:
            rows.append({"name": name, "configured": False, "kind": "unknown", "live_tested": False,
                         "note": "Unknown provider name; ignored."})
    return rows


# ---------------------------------------------------------------- checking and reporting
def run_check(normalized: str, domain: str, notes: list[str], providers: list, events=None, correlation_id=None) -> dict:
    results: list[ProviderResult] = []
    for p in providers:
        try:
            res = p.check(normalized, domain, notes)
        except Exception as exc:         # a provider bug must not break the request
            res = ProviderResult(getattr(p, "name", "unknown"), "error", "inconclusive",
                                 f"The provider failed ({type(exc).__name__}).", getattr(p, "name", "unknown"))
        if res.status == "error" and events is not None:
            events.record("medium", "provider", "provider.failure", f"ScamWatch provider '{res.provider}' failed: {res.detail}",
                          correlation_id=correlation_id, details={"provider": res.provider})
        results.append(res)
    answered = [r for r in results if r.status == "ok"]
    verdict = max((r.verdict for r in answered), key=lambda v: VERDICT_RANK[v]) if answered else "inconclusive"
    return {"normalized_url": normalized, "domain": domain, "verdict": verdict, "notes": notes,
            "providers": [asdict(r) for r in results],
            "provider_errors": [r.provider for r in results if r.status == "error"],
            "simulated": any(r.simulated for r in results), "disclaimer": DISCLAIMER}


def report_out(r: ScamReport, include_notes: bool) -> dict:
    return {"id": r.id, "normalized_url": r.normalized_url, "domain": r.domain, "report_count": r.report_count,
            "first_reported_at": r.first_reported_at, "last_reported_at": r.last_reported_at, "verdict": r.verdict,
            "providers": json.loads(r.provider_summary_json or "[]"), "review_status": r.review_status,
            "analyst_notes": r.analyst_notes if include_notes else "", "reviewed_at": r.reviewed_at,
            "reporter_comment": r.reporter_comment, "disclaimer": DISCLAIMER}


def submit_report(session: Session, user, raw_url: str, comment: str, providers: list, events=None,
                  correlation_id=None) -> tuple[ScamReport, bool, dict]:
    """Returns (report, was_duplicate, check_result)."""
    try:
        normalized, domain, notes = normalize_url(raw_url)
    except InvalidUrl as exc:
        raise HTTPException(422, str(exc))
    check = run_check(normalized, domain, notes, providers, events, correlation_id)
    h = url_hash(normalized)
    existing = session.scalar(select(ScamReport).where(ScamReport.url_hash == h))
    duplicate = existing is not None
    if existing is None:
        report = ScamReport(normalized_url=normalized, url_hash=h, domain=domain, reporter_id=user.id,
                            reporter_comment=comment[:1000], verdict=check["verdict"],
                            provider_summary_json=json.dumps(check["providers"], default=str))
        try:
            with session.begin_nested():
                session.add(report)
                session.flush()
        except IntegrityError:           # a concurrent identical report won the race
            existing = session.scalar(select(ScamReport).where(ScamReport.url_hash == h))
            duplicate = True
    if existing is not None:
        report = existing
        report.report_count += 1
        report.last_reported_at = utcnow()
        if VERDICT_RANK[check["verdict"]] > VERDICT_RANK.get(report.verdict, 0):
            report.verdict = check["verdict"]
            report.provider_summary_json = json.dumps(check["providers"], default=str)
    record_audit(session, actor=user, action="scamwatch.reported", entity_type="scam_report", entity_id=report.id,
                 after={"domain": domain, "duplicate": duplicate, "verdict": report.verdict, "count": report.report_count},
                 correlation_id=correlation_id)
    severity = {"malicious": "high", "suspicious": "medium"}.get(report.verdict)
    if severity is None and report.report_count >= 3:
        severity = "medium"
    if severity:
        ensure_case(session, source_type="scamwatch_report", source_record_id=str(report.id), severity=severity,
                    summary=f"Reported website {report.domain} (verdict: {report.verdict}, {report.report_count} report(s))",
                    evidence_reference=f"scam_report:{report.id}", correlation_id=correlation_id)
    session.flush()
    return report, duplicate, check


def list_reports(session: Session, user, *, review_status=None, verdict=None, search=None, page=1, page_size=20):
    q = select(ScamReport)
    if not user.has("scamwatch.view_all"):
        q = q.where(ScamReport.reporter_id == user.id)
    if review_status:
        q = q.where(ScamReport.review_status == review_status)
    if verdict:
        q = q.where(ScamReport.verdict == verdict)
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").lower() + "%"
        q = q.where(or_(func.lower(ScamReport.domain).like(like, escape="\\"),
                        func.lower(ScamReport.normalized_url).like(like, escape="\\")))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(ScamReport.last_reported_at.desc(), ScamReport.id.desc())
                           .limit(page_size).offset((page - 1) * page_size)).all()
    return rows, total


def get_report(session: Session, user, report_id: int) -> ScamReport:
    r = session.get(ScamReport, report_id)
    if r is None or (not user.has("scamwatch.view_all") and r.reporter_id != user.id):
        raise HTTPException(404, "Report not found")
    return r


def review_report(session: Session, user, report_id: int, review_status: str, notes: str | None, correlation_id=None):
    if review_status not in REVIEW_STATUSES:
        raise HTTPException(422, "invalid review_status")
    r = session.get(ScamReport, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    before = {"review_status": r.review_status}
    r.review_status = review_status
    if notes is not None:
        r.analyst_notes = notes
    r.reviewed_by, r.reviewed_at = user.id, utcnow()
    record_audit(session, actor=user, action="scamwatch.reviewed", entity_type="scam_report", entity_id=r.id,
                 before=before, after={"review_status": review_status}, correlation_id=correlation_id)
    if review_status == "reviewed_malicious":
        ensure_case(session, source_type="scamwatch_report", source_record_id=str(r.id), severity="high",
                    summary=f"Analyst-confirmed malicious website {r.domain}", evidence_reference=f"scam_report:{r.id}",
                    correlation_id=correlation_id)
    session.flush()
    return r
