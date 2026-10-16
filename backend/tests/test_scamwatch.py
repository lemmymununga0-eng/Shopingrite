"""ScamWatch: normalisation, providers (mocked), reports, duplicates, review, and the no-fetch guarantee.
Provider results here come from a clearly labelled MOCK provider; no live threat feed was contacted."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services import scamwatch_service as sw

from .conftest import auth, cust


@pytest.mark.parametrize("raw,expected", [
    ("Example.COM", "http://example.com/"),
    ("https://EXAMPLE.com:443/Path?b=2&a=1&utm_source=x#frag", "https://example.com/Path?a=1&b=2"),
    ("http://example.com:8080/x", "http://example.com:8080/x"),
    ("  https://example.com/a  ", "https://example.com/a"),
    ("https://bücher.example/", "https://xn--bcher-kva.example/"),
])
def test_normalization(raw, expected):
    assert sw.normalize_url(raw)[0] == expected


@pytest.mark.parametrize("raw", ["", "   ", "javascript:alert(1)", "data:text/html,hi", "file:///etc/passwd", "ftp://example.com",
                                 "http://localhost/", "http://127.0.0.1/", "http://10.0.0.5/admin", "http://169.254.169.254/latest",
                                 "http://[::1]/", "http://intranet/", "http://printer.local/", "exa mple.com", "http://",
                                 "https://" + "a" * 70 + ".com", "x" * 2100, "http://exa\x00mple.com"])
def test_invalid_or_internal_urls_rejected(raw):
    with pytest.raises(sw.InvalidUrl):
        sw.normalize_url(raw)


def test_userinfo_trick_is_flagged():
    n, d, notes = sw.normalize_url("http://paypal.com@evil.example/login")
    assert d == "evil.example" and "contains_credentials_in_url" in notes


@pytest.fixture()
def mock_client(settings):
    settings.scamwatch_providers = "heuristic"
    provider = sw.MockProvider({"bad.example": "malicious", "iffy.example": "suspicious"})
    with TestClient(create_app(settings, providers=[provider])) as c:
        yield c


def test_check_returns_provider_status_source_and_disclaimer(mock_client):
    r = mock_client.post("/scamwatch/check", json={"url": "bad.example/x"}, headers=cust())
    d = r.json()
    assert r.status_code == 200 and d["verdict"] == "malicious" and d["simulated"] is True
    assert d["providers"][0]["provider"] == "mock" and d["providers"][0]["source"] == "mock"
    assert "does not mean a website is safe" in d["disclaimer"]


def test_no_known_threat_is_never_called_safe(mock_client):
    d = mock_client.post("/scamwatch/check", json={"url": "fine.example"}, headers=cust()).json()
    assert d["verdict"] == "no_known_threat" and d["verdict"] != "safe"
    assert "safe" in d["disclaimer"].lower() and "not" in d["disclaimer"].lower()


def test_check_is_not_saved(mock_client):
    mock_client.post("/scamwatch/check", json={"url": "bad.example"}, headers=cust())
    assert mock_client.get("/scamwatch/reports", headers=auth("s", "security_analyst")).json()["total"] == 0


def test_invalid_url_gives_clear_422_and_event(mock_client):
    r = mock_client.post("/scamwatch/check", json={"url": "http://127.0.0.1/"}, headers=cust())
    assert r.status_code == 422 and "Private" in r.json()["detail"]
    ev = mock_client.get("/security/events?category=input", headers=auth("s", "security_analyst")).json()
    assert any(e["event_type"] == "input.invalid_url" for e in ev["items"])


def test_report_persists_and_opens_case_for_malicious(mock_client):
    r = mock_client.post("/scamwatch/reports", json={"url": "https://bad.example/win", "comment": "got an SMS"}, headers=cust())
    assert r.status_code == 201 and r.json()["duplicate"] is False
    rid = r.json()["report"]["id"]
    staff = auth("s", "security_analyst")
    assert mock_client.get(f"/scamwatch/reports/{rid}", headers=staff).json()["verdict"] == "malicious"
    cases = mock_client.get("/investigations?source_type=scamwatch_report", headers=staff).json()
    assert cases["total"] == 1 and cases["items"][0]["severity"] == "high"


def test_duplicate_reports_increment_count_without_new_rows(mock_client):
    a = mock_client.post("/scamwatch/reports", json={"url": "http://bad.example/x?utm_campaign=q"}, headers=cust("a")).json()
    b = mock_client.post("/scamwatch/reports", json={"url": "HTTP://BAD.example/x"}, headers=cust("b"))
    assert b.status_code == 200 and b.json()["duplicate"] is True and b.json()["report"]["report_count"] == 2
    staff = auth("s", "security_analyst")
    assert mock_client.get("/scamwatch/reports", headers=staff).json()["total"] == 1
    assert mock_client.get("/investigations?source_type=scamwatch_report", headers=staff).json()["total"] == 1


def test_three_reports_of_an_unknown_site_open_a_case(mock_client):
    for i in range(3):
        mock_client.post("/scamwatch/reports", json={"url": "unknown.example"}, headers=cust(f"u{i}"))
    staff = auth("s", "security_analyst")
    assert mock_client.get("/investigations?source_type=scamwatch_report", headers=staff).json()["total"] == 1


def test_customers_see_only_their_own_reports_and_no_analyst_notes(mock_client):
    r = mock_client.post("/scamwatch/reports", json={"url": "bad.example"}, headers=cust("a")).json()["report"]
    mock_client.post("/scamwatch/reports", json={"url": "iffy.example"}, headers=cust("b"))
    assert mock_client.get("/scamwatch/reports", headers=cust("a")).json()["total"] == 1
    assert mock_client.get(f"/scamwatch/reports/{r['id']}", headers=cust("b")).status_code == 404
    mock_client.patch(f"/scamwatch/reports/{r['id']}", json={"review_status": "reviewed_malicious", "notes": "internal"},
                      headers=auth("s", "security_analyst"))
    assert mock_client.get(f"/scamwatch/reports/{r['id']}", headers=cust("a")).json()["analyst_notes"] == ""
    assert mock_client.get(f"/scamwatch/reports/{r['id']}", headers=auth("s", "security_analyst")).json()["analyst_notes"] == "internal"


def test_review_needs_permission_and_is_audited(mock_client):
    r = mock_client.post("/scamwatch/reports", json={"url": "bad.example"}, headers=cust()).json()["report"]
    body = {"review_status": "reviewed_benign", "notes": "checked, legitimate"}
    for who in (cust(), auth("f", "fraud_analyst")):
        assert mock_client.patch(f"/scamwatch/reports/{r['id']}", json=body, headers=who).status_code == 403
    assert mock_client.patch(f"/scamwatch/reports/{r['id']}", json=body, headers=auth("s", "security_analyst")).status_code == 200
    audit = mock_client.get("/audit?action=scamwatch.reviewed", headers=auth("s", "security_analyst")).json()
    assert audit["total"] == 1
    assert mock_client.patch(f"/scamwatch/reports/{r['id']}", json={"review_status": "bogus"}, headers=auth("s", "security_analyst")).status_code == 422


def test_provider_failure_is_inconclusive_and_recorded(settings):
    with TestClient(create_app(settings, providers=[sw.MockProvider(fail=True)])) as c:
        d = c.post("/scamwatch/check", json={"url": "x.example"}, headers=cust()).json()
        assert d["verdict"] == "inconclusive" and d["provider_errors"] == ["mock"]
        ev = c.get("/security/events?category=provider", headers=auth("s", "security_analyst")).json()
        assert ev["total"] == 1 and ev["items"][0]["severity"] == "medium"
        rep = c.post("/scamwatch/reports", json={"url": "x.example"}, headers=cust())
        assert rep.status_code == 201 and rep.json()["report"]["verdict"] == "inconclusive"


def test_a_crashing_provider_does_not_break_the_request(settings):
    class Broken:
        name = "broken"

        def check(self, *a):
            raise RuntimeError("boom with secret-key-123")

    with TestClient(create_app(settings, providers=[Broken()])) as c:
        r = c.post("/scamwatch/check", json={"url": "x.example"}, headers=cust())
        assert r.status_code == 200 and "secret-key-123" not in r.text and r.json()["verdict"] == "inconclusive"


def test_heuristic_flags_brand_lookalike_but_not_the_official_domain():
    h = sw.HeuristicProvider(["shoprite"], ["shoprite.co.za"])
    bad = h.check(*sw.normalize_url("http://shoprite-gift-voucher.top/claim"))
    assert bad.verdict == "suspicious" and any("brand" in s for s in bad.signals)
    ok = h.check(*sw.normalize_url("https://www.shoprite.co.za/"))
    assert ok.verdict == "inconclusive" and not any("brand" in s for s in ok.signals)
    assert "does not mean the site is safe" in ok.detail


def test_heuristic_never_returns_safe_or_malicious():
    h = sw.HeuristicProvider([], [])
    for u in ("https://example.com", "http://203.0.114.1/", "http://a.b.c.d.e.f.top/verify-account-login"):
        try:
            n = sw.normalize_url(u)
        except sw.InvalidUrl:
            continue
        assert h.check(*n).verdict in ("inconclusive", "suspicious")


def test_submitted_url_is_never_fetched(settings, monkeypatch):
    """No outbound HTTP at all with the heuristic provider: the URL is data, not a fetch target (no SSRF surface)."""
    def forbid(*a, **k):
        raise AssertionError("outbound request attempted")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbid)        # real network transports only;
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbid)   # the test client uses its own
    with TestClient(create_app(settings)) as c:
        for u in ("http://169.254.169.254/", "https://example.com/", "http://evil.example/redirect?to=http://127.0.0.1"):
            c.post("/scamwatch/check", json={"url": u}, headers=cust())
            c.post("/scamwatch/reports", json={"url": u}, headers=cust())


def test_safe_browsing_adapter_with_mock_transport():
    """MOCKED HTTP. Proves request shape and error handling only; it does not prove the live API works."""
    seen = {}

    def handler(request: httpx.Request):
        seen["host"], seen["body"] = request.url.host, json.loads(request.content)
        return httpx.Response(200, json={"matches": [{"threatType": "SOCIAL_ENGINEERING"}]})

    p = sw.SafeBrowsingProvider("KEY123", httpx.Client(transport=httpx.MockTransport(handler)))
    res = p.check("http://evil.example/", "evil.example", [])
    assert res.verdict == "malicious" and seen["host"] == "safebrowsing.googleapis.com"
    assert seen["body"]["threatInfo"]["threatEntries"] == [{"url": "http://evil.example/"}]
    clean = sw.SafeBrowsingProvider("K", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    assert clean.check("http://a.example/", "a.example", []).verdict == "no_known_threat"


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, content=b"not json"), httpx.Response(403, json={})])
def test_safe_browsing_errors_are_inconclusive_and_leak_no_key(response):
    p = sw.SafeBrowsingProvider("SUPERSECRETKEY", httpx.Client(transport=httpx.MockTransport(lambda r: response)))
    res = p.check("http://a.example/", "a.example", [])
    assert res.status == "error" and res.verdict == "inconclusive" and "SUPERSECRETKEY" not in json.dumps(res.__dict__)


def test_safe_browsing_timeout_and_missing_key():
    def timeout(request):
        raise httpx.ConnectTimeout("t", request=request)
    p = sw.SafeBrowsingProvider("K", httpx.Client(transport=httpx.MockTransport(timeout)))
    assert "timed out" in p.check("http://a.example/", "a.example", []).detail
    assert sw.SafeBrowsingProvider("").check("http://a.example/", "a.example", []).status == "skipped"


def test_provider_status_reports_unverified_live_state(settings):
    settings.scamwatch_providers = "heuristic,safebrowsing,weird"
    rows = {r["name"]: r for r in sw.provider_status(settings)}
    assert rows["safebrowsing"]["configured"] is False and rows["safebrowsing"]["live_tested"] is False
    assert rows["weird"]["configured"] is False


def test_scamwatch_rate_limited(settings):
    settings.scamwatch_rate_limit_per_min = 2
    with TestClient(create_app(settings)) as c:
        codes = [c.post("/scamwatch/check", json={"url": "a.example"}, headers=cust()).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes[2:]


def test_scamwatch_requires_sign_in_and_validates_body(client):
    assert client.post("/scamwatch/check", json={"url": "a.example"}).status_code == 401
    assert client.post("/scamwatch/check", json={"url": "a.example", "x": 1}, headers=cust()).status_code == 422
    assert client.post("/scamwatch/check", json={}, headers=cust()).status_code == 422
