"""Dataset adapters: the ONLY place that knows how a raw public dataset becomes a TaskSpec.

Each adapter states, in code and in the model metadata:
  * which file it reads and the checksum recorded when it was downloaded (a file that no longer matches is refused);
  * the label and which value means fraud/phishing;
  * which columns the model may use because they exist BEFORE the event being judged, and which are excluded and why;
  * how duplicates are handled before the split so they cannot sit on both sides.

Three adapters:
  creditcard-openml : real, anonymised card transactions (Time, V1-V28, Amount). Needs no account to download.
  paysim            : simulated mobile-money transactions. Needs a Kaggle download; the adapter and its tests exist, training is
                      BLOCKED until the file is on disk.
  phiusiil          : phishing vs legitimate URLs, for ScamWatch. A DIFFERENT task from payment fraud: never mixed with it.
"""
import hashlib
import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier  # noqa: F401  (re-exported for tests)
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline

from .framework import Candidate, SEED, TaskSpec

EXTERNAL_DIR = Path(__file__).resolve().parents[2] / "data" / "external"


class DatasetUnavailable(Exception):
    """The dataset has not been downloaded, or no longer matches its recorded checksum."""


def load_manifest(name: str, root: Path = EXTERNAL_DIR) -> dict:
    p = Path(root) / name / "MANIFEST.json"
    if not p.exists():
        raise DatasetUnavailable(f"Dataset '{name}' has not been downloaded. Run: python scripts/fetch_datasets.py get {name} --accept-licence")
    return json.loads(p.read_text(encoding="utf8"))


def verified_file(name: str, filename: str, root: Path = EXTERNAL_DIR) -> tuple[Path, dict]:
    """Return the dataset file only if its SHA-256 matches the manifest written at download time."""
    manifest = load_manifest(name, root)
    entry = next((f for f in manifest.get("files", []) if f["file"] == filename), None)
    path = Path(root) / name / filename
    if entry is None or not path.exists():
        raise DatasetUnavailable(f"{filename} is missing from the '{name}' download.")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != entry["sha256"]:
        raise DatasetUnavailable(f"{filename} no longer matches the checksum recorded at download time: re-download it.")
    return path, {"name": name, "source": manifest.get("source"), "terms": manifest.get("terms"), "licence": manifest.get("licence"),
                  "licence_status": manifest.get("licence_status"), "sha256": entry["sha256"], "file": filename,
                  "downloaded_at": manifest.get("downloaded_at"), "attribution_file": f"data/external/{name}/ATTRIBUTION.txt"}


def drop_exact_duplicates(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, dict]:
    """Remove rows identical in every listed column BEFORE splitting, so the same row cannot be in both train and test."""
    before = len(df)
    out = df.drop_duplicates(subset=cols).reset_index(drop=True)
    return out, {"rows_before": int(before), "dropped_exact_duplicates": int(before - len(out)), "rows_after": int(len(out))}


def _numeric_labels(s: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(s.astype(str), errors="coerce")
    if out.isna().any() or not set(out.unique().tolist()) <= {0, 1}:
        raise ValueError(f"Label column '{name}' must contain only 0 and 1; found {sorted(set(s.astype(str).unique()))[:6]}.")
    return out.astype(int)


# =============================================================================================== credit card (PCA features)
CC_V = [f"V{i}" for i in range(1, 29)]
CC_INPUTS = ["Time"] + CC_V + ["Amount"]


def _cc_features(X: pd.DataFrame) -> pd.DataFrame:
    """Same transformation at training and prediction time. `Time` is seconds since the dataset's first transaction, so only its
    position within a 24-hour cycle is kept (the absolute value would let a model learn 'when in the dataset', which is useless live)."""
    hour = (pd.to_numeric(X["Time"]) // 3600) % 24
    out = X[CC_V].astype(float).copy()
    out["log_amount"] = np.log1p(pd.to_numeric(X["Amount"]).clip(lower=0))
    out["cycle_hour_sin"] = np.sin(2 * math.pi * hour / 24)
    out["cycle_hour_cos"] = np.cos(2 * math.pi * hour / 24)
    return out


def _cc_pre():
    return Pipeline([("features", FunctionTransformer(_cc_features, validate=False)), ("scale", StandardScaler())])


def candidates_default(fast: bool = False) -> list[Candidate]:
    n = 40 if fast else 150
    return [
        Candidate("logistic_regression", lambda **p: LogisticRegression(class_weight="balanced", max_iter=1000, solver="lbfgs", **p),
                  [{"C": 0.1}, {"C": 1.0}], "interpretable baseline"),
        Candidate("random_forest", lambda **p: RandomForestClassifier(n_estimators=n, class_weight="balanced_subsample", n_jobs=-1, random_state=SEED, **p),
                  [{"min_samples_leaf": 2, "max_depth": None}] if fast else [{"min_samples_leaf": 2, "max_depth": None}, {"min_samples_leaf": 5, "max_depth": 14}]),
        Candidate("hist_gradient_boosting", lambda **p: HistGradientBoostingClassifier(class_weight="balanced", random_state=SEED, **p),
                  [{"max_leaf_nodes": 31, "learning_rate": 0.1, "max_iter": 60 if fast else 200}] if fast else
                  [{"max_leaf_nodes": 31, "learning_rate": 0.1, "max_iter": 200}, {"max_leaf_nodes": 15, "learning_rate": 0.05, "max_iter": 300}]),
    ]


def creditcard_task(df: pd.DataFrame, dataset: dict, fast: bool = False, is_fixture: bool = False) -> TaskSpec:
    missing = [c for c in CC_INPUTS + ["Class"] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing columns: {missing[:6]}")
    work = df[CC_INPUTS + ["Class"]].copy()
    for c in CC_INPUTS:
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work["Class"] = _numeric_labels(work["Class"], "Class")
    bad = int(work.isna().any(axis=1).sum()) + int(np.isinf(work[CC_INPUTS].to_numpy()).any(axis=1).sum())
    work = work.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    work, dup = drop_exact_duplicates(work, CC_INPUTS + ["Class"])
    cleaning = {**dup, "dropped_missing_or_infinite_rows": bad, "raw_rows_in_file": int(len(df))}
    order = work["Time"].to_numpy()
    return TaskSpec(
        model_name="creditcard_pca", task="Financial transaction fraud detection (anonymised card transactions)", dataset={**dataset, "rows_raw": int(len(df))},
        X=work[CC_INPUTS].reset_index(drop=True), y=work["Class"].rename("Class"), input_features=list(CC_INPUTS),
        feature_types={c: "float" for c in CC_INPUTS}, preprocessor=_cc_pre, candidates=candidates_default(fast),
        target_definition="Class = 1 means the transaction was confirmed fraudulent by the data owners; 0 = legitimate",
        preprocessing_description="Time is converted to a position in a 24-hour cycle (sin/cos) and then dropped; Amount is log1p-transformed; V1-V28 are "
                                  "used as given; everything is standardised using training-partition statistics only (fitted inside the pipeline).",
        excluded_features=[{"name": "Time (raw seconds)", "reason": "Seconds since the first transaction of the dataset: not portable to live data and lets a model learn the position in the collection period."}],
        derived_features=[{"name": "log_amount", "from": "Amount"}, {"name": "cycle_hour_sin/cos", "from": "Time"}],
        cleaning=cleaning, order=order, min_pr_auc=0.6, is_fixture=is_fixture,
        source_note="Real card transactions from two days in September 2013 by European cardholders; V1-V28 are anonymised PCA components.",
        limitations=["V1-V28 are anonymised: the model cannot be applied to anything except rows that already contain them. It cannot score grocery-store orders.",
                     "Only two days of 2013 data: patterns may not hold for other times, countries or payment channels.",
                     "No cardholder or merchant identifiers: transactions of the same card can fall on both sides of the split, which may make results optimistic.",
                     f"Fraud is {100 * float((work['Class'] == 1).mean()):.3f}% of the cleaned rows: precision at a given recall is unstable with only a few dozen test fraud cases."])


# ======================================================================================================== PaySim (mobile money)
PS_INPUTS = ["type", "amount", "oldbalanceOrg", "oldbalanceDest", "hour_of_day", "dest_is_merchant"]
PS_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]
PS_RAW = ["step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig", "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud"]


def paysim_inputs(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw PaySim columns -> the six inputs a live mobile-money event could provide BEFORE it completes."""
    out = pd.DataFrame({
        "type": raw["type"].astype(str).str.upper().str.replace("-", "_", regex=False),
        "amount": pd.to_numeric(raw["amount"]), "oldbalanceOrg": pd.to_numeric(raw["oldbalanceOrg"]),
        "oldbalanceDest": pd.to_numeric(raw["oldbalanceDest"]),
        "hour_of_day": (pd.to_numeric(raw["step"]) % 24).astype(int),
        "dest_is_merchant": raw["nameDest"].astype(str).str.startswith("M").astype(int)})
    return out[PS_INPUTS]


def _ps_features(X: pd.DataFrame) -> pd.DataFrame:
    out = X.copy()
    out["amount_to_oldbalance"] = out["amount"] / (out["oldbalanceOrg"].clip(lower=0) + 1.0)     # draining the whole account is the classic pattern
    out["empties_account"] = (out["amount"] >= out["oldbalanceOrg"] - 0.01).astype(int) * (out["oldbalanceOrg"] > 0).astype(int)
    out["log_amount"] = np.log1p(out["amount"].clip(lower=0))
    out["log_old_orig"] = np.log1p(out["oldbalanceOrg"].clip(lower=0))
    out["log_old_dest"] = np.log1p(out["oldbalanceDest"].clip(lower=0))
    return out.drop(columns=["amount", "oldbalanceOrg", "oldbalanceDest"])


def _ps_pre():
    num = Pipeline([("scale", StandardScaler())])
    return Pipeline([("features", FunctionTransformer(_ps_features, validate=False)),
                     ("cols", ColumnTransformer([("type", OneHotEncoder(categories=[PS_TYPES], handle_unknown="error"), ["type"]),
                                                 ("num", num, ["hour_of_day", "dest_is_merchant", "amount_to_oldbalance", "empties_account", "log_amount", "log_old_orig", "log_old_dest"])]))])


def paysim_task(raw: pd.DataFrame, dataset: dict, fast: bool = False, is_fixture: bool = False) -> TaskSpec:
    missing = [c for c in PS_RAW if c not in raw.columns]
    if missing:
        raise ValueError(f"PaySim file is missing columns: {missing}")
    y = _numeric_labels(raw["isFraud"], "isFraud")
    X = paysim_inputs(raw)
    unknown = sorted(set(X["type"]) - set(PS_TYPES))
    if unknown:
        raise ValueError(f"Unknown transaction types: {unknown}")
    frame = X.assign(isFraud=y.to_numpy())
    frame, dup = drop_exact_duplicates(frame, PS_INPUTS + ["isFraud"])
    # exact duplicates are rare in PaySim; the chronological order is only available when no rows were dropped
    order = pd.to_numeric(raw["step"]).to_numpy() if dup["dropped_exact_duplicates"] == 0 else None
    return TaskSpec(
        model_name="paysim_mobile_money", task="Mobile-money transaction fraud detection (simulated data)", dataset={**dataset, "rows_raw": int(len(raw))},
        X=frame[PS_INPUTS].reset_index(drop=True), y=frame["isFraud"].rename("isFraud"), input_features=list(PS_INPUTS),
        feature_types={"type": "category", "amount": "float", "oldbalanceOrg": "float", "oldbalanceDest": "float", "hour_of_day": "int", "dest_is_merchant": "int"},
        preprocessor=_ps_pre, candidates=[c for c in candidates_default(fast) if c.name != "random_forest"] if not fast else candidates_default(True),
        target_definition="isFraud = 1 means the simulator labelled the transaction as fraudulent; 0 = legitimate",
        preprocessing_description="type is one-hot encoded; amount, balances and the engineered amount/balance ratio are log-scaled and standardised with "
                                  "training-partition statistics only.",
        excluded_features=[
            {"name": "newbalanceOrig", "reason": "Balance AFTER the transaction. The dataset documents that detected fraud is cancelled, so this column encodes the answer."},
            {"name": "newbalanceDest", "reason": "Balance AFTER the transaction: post-event information, unavailable at decision time."},
            {"name": "isFlaggedFraud", "reason": "The output of a simulated rule (transfers over 200,000): a proxy for the label, not an input."},
            {"name": "nameOrig / nameDest", "reason": "Account identifiers. Only whether the destination is a merchant ('M' prefix) is kept."},
            {"name": "step (raw)", "reason": "Hours since the simulation began: only the 24-hour position (hour_of_day) is kept."}],
        derived_features=[{"name": "hour_of_day", "from": "step"}, {"name": "dest_is_merchant", "from": "nameDest"},
                          {"name": "amount_to_oldbalance, empties_account", "from": "amount, oldbalanceOrg"}],
        cleaning=dup, order=order, min_pr_auc=0.5, is_fixture=is_fixture,
        source_note="PaySim: simulated mobile-money transactions generated from aggregates of real logs of an African provider.",
        limitations=["Simulated data: fraud follows the simulator's rules (fraud occurs only in TRANSFER and CASH_OUT), so results are optimistic for real traffic.",
                     "Needs the customer's pre-transaction balance, which the grocery store does not have: it cannot score store orders."])


# ===================================================================================================== URLs (ScamWatch)
_KEYWORDS = ("login", "signin", "verify", "secure", "account", "update", "bank", "confirm", "wallet", "password", "paypal", "support")
_COMMON_TLDS = {"com", "org", "net", "edu", "gov", "co", "uk", "io", "info"}


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return float(-sum((c / n) * math.log2(c / n) for c in Counter(s).values()))


def url_features_one(url: str) -> dict:
    """Features computed ONLY from the URL text (ScamWatch never opens a link). The same function runs at training and prediction time."""
    raw = (url or "").strip()
    try:
        parsed = urlsplit(raw if "://" in raw else "http://" + raw)
    except ValueError:                           # e.g. "http://[::1": hostile or broken input must never crash the scorer
        parsed = urlsplit("http://invalid.invalid")
    host = (parsed.hostname or "").lower()
    path, query = parsed.path or "", parsed.query or ""
    labels = [x for x in host.split(".") if x]
    tld = labels[-1] if labels else ""
    host_core = host[4:] if host.startswith("www.") else host
    low = raw.lower()
    n = max(len(raw), 1)
    return {
        "url_len": len(raw), "host_len": len(host), "path_len": len(path), "query_len": len(query), "path_depth": path.count("/"),
        "n_dots": raw.count("."), "n_hyphens": raw.count("-"), "n_underscores": raw.count("_"), "n_at": raw.count("@"), "n_equals": raw.count("="),
        "n_qmark": raw.count("?"), "n_amp": raw.count("&"), "n_percent": raw.count("%"), "n_digits": sum(c.isdigit() for c in raw),
        "digit_ratio": sum(c.isdigit() for c in raw) / n, "letter_ratio": sum(c.isalpha() for c in raw) / n,
        "n_special": sum(not c.isalnum() for c in raw), "n_subdomains": max(len(labels) - 2, 0),
        "host_is_ip": int(bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host))), "is_https": int(parsed.scheme == "https"),
        "has_port": int(parsed.port not in (None, 80, 443)) if _safe_port(parsed) else 0, "has_punycode": int("xn--" in host),
        "host_digit_ratio": sum(c.isdigit() for c in host) / max(len(host), 1), "host_hyphens": host.count("-"),
        "host_entropy": _entropy(host_core), "longest_label": max((len(x) for x in labels), default=0), "tld_len": len(tld),
        "tld_common": int(tld in _COMMON_TLDS), "keyword_count": sum(k in low for k in _KEYWORDS),
        "has_double_slash_in_path": int("//" in path), "has_www": int(host.startswith("www.")),
    }


def _safe_port(parsed) -> bool:
    try:
        parsed.port
        return True
    except ValueError:
        return False


URL_FEATURE_NAMES = list(url_features_one("http://example.com").keys())


@lru_cache(maxsize=500_000)
def _url_row(url: str) -> tuple:
    f = url_features_one(url)
    return tuple(f[k] for k in URL_FEATURE_NAMES)


def _url_features(X: pd.DataFrame) -> pd.DataFrame:
    """Cached per URL: cross-validation refits the pipeline many times, and each URL is only parsed once."""
    return pd.DataFrame([_url_row(u) for u in X["url"].astype(str)], columns=URL_FEATURE_NAMES)


def _url_pre():
    return Pipeline([("features", FunctionTransformer(_url_features, validate=False)), ("scale", StandardScaler())])


# Host-name-only features. In the PhiUSIIL data every legitimate address is "https://www.<domain>" with no path and no trailing slash, so the
# protocol, the "www." prefix, the path and the trailing slash separate the classes by how the lists were built, not by anything about phishing
# (see docs/ML_EVALUATION.md). The canonical host below ignores all of them.
HOST_FEATURE_NAMES = ["host_len", "n_subdomains", "host_is_ip", "has_punycode", "host_digit_ratio", "host_hyphens", "host_entropy", "longest_label", "tld_len", "tld_common"]


def canonical_host(url: str) -> str:
    raw = (url or "").strip()
    try:
        parsed = urlsplit(raw if "://" in raw else "http://" + raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        host = ""
    return host[4:] if host.startswith("www.") else host


def url_host_features_one(url: str) -> dict:
    host = canonical_host(url)
    labels = [x for x in host.split(".") if x]
    tld = labels[-1] if labels else ""
    return {"host_len": len(host), "n_subdomains": max(len(labels) - 2, 0), "host_is_ip": int(bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host))),
            "has_punycode": int("xn--" in host), "host_digit_ratio": sum(c.isdigit() for c in host) / max(len(host), 1), "host_hyphens": host.count("-"),
            "host_entropy": _entropy(host), "longest_label": max((len(x) for x in labels), default=0), "tld_len": len(tld), "tld_common": int(tld in _COMMON_TLDS)}


@lru_cache(maxsize=500_000)
def _url_host_row(url: str) -> tuple:
    f = url_host_features_one(url)
    return tuple(f[k] for k in HOST_FEATURE_NAMES)


def _url_host_features(X: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([_url_host_row(u) for u in X["url"].astype(str)], columns=HOST_FEATURE_NAMES)


def _url_host_pre():
    return Pipeline([("features", FunctionTransformer(_url_host_features, validate=False)), ("scale", StandardScaler())])


# ---- robustness gate: cosmetic changes must not decide the verdict
def _rebuild(parsed, scheme=None, netloc=None, path=None, query=None) -> str:
    from urllib.parse import urlunsplit
    return urlunsplit((scheme if scheme is not None else parsed.scheme, netloc if netloc is not None else parsed.netloc,
                       path if path is not None else parsed.path, query if query is not None else parsed.query, ""))


def _parse(u: str):
    return urlsplit(u if "://" in u else "http://" + u)


COSMETIC_CHANGES_LEGIT = {
    "remove the www prefix": lambda u: _rebuild(_parse(u), netloc=_parse(u).netloc[4:] if _parse(u).netloc.lower().startswith("www.") else _parse(u).netloc),
    "use http instead of https": lambda u: _rebuild(_parse(u), scheme="http"),
    "add a trailing slash": lambda u: _rebuild(_parse(u), path=_parse(u).path or "/"),
    "add a path": lambda u: _rebuild(_parse(u), path=_parse(u).path if _parse(u).path not in ("", "/") else "/products/index.html"),
}


def _as_legit_template(u: str) -> str:
    p = _parse(u)
    host = p.netloc[4:] if p.netloc.lower().startswith("www.") else p.netloc
    return _rebuild(p, scheme="https", netloc="www." + host, path="", query="")


def url_invariance_checks(score, legit_urls: list[str], phishing_urls: list[str], threshold: float, max_rise: float = 0.05, min_keep: float = 0.8) -> list[dict]:
    """`score(list_of_urls) -> probabilities`. A model that learned how a dataset's addresses were formatted will flag ordinary legitimate
    addresses after a cosmetic change, and will wave through phishing addresses dressed in the legitimate format. Both are refused here."""
    checks = []
    base = float((np.asarray(score(legit_urls)) >= threshold).mean()) if legit_urls else 0.0
    for name, fn in COSMETIC_CHANGES_LEGIT.items():
        share = float((np.asarray(score([fn(u) for u in legit_urls])) >= threshold).mean()) if legit_urls else 0.0
        checks.append({"check": f"legitimate addresses stay unflagged when we {name}", "passed": bool(share - base <= max_rise),
                       "detail": f"flagged {100 * share:.1f}% (unchanged addresses: {100 * base:.1f}%); allowed rise {100 * max_rise:.0f} points"})
    if phishing_urls:
        kept0 = float((np.asarray(score(phishing_urls)) >= threshold).mean())
        kept1 = float((np.asarray(score([_as_legit_template(u) for u in phishing_urls])) >= threshold).mean())
        checks.append({"check": "phishing addresses are still flagged when rewritten as https://www.<host>", "passed": bool(kept1 >= min_keep * kept0),
                       "detail": f"flagged {100 * kept1:.1f}% after rewriting, {100 * kept0:.1f}% before; must keep {int(100 * min_keep)}% of the original rate"})
    return checks


def phiusiil_task(df: pd.DataFrame, dataset: dict, fast: bool = False, is_fixture: bool = False, max_rows: int | None = None,
                  feature_set: str = "host") -> TaskSpec:
    """feature_set "host" (default): 10 features of the canonical host name only. "lexical": the 31 whole-address features, which the paper
    shows mostly measure how the dataset's addresses were formatted; kept for the comparison, never promoted without passing the invariance gate."""
    if feature_set not in ("host", "lexical"):
        raise ValueError("feature_set must be 'host' or 'lexical'")
    host_only = feature_set == "host"
    for c in ("URL", "label", "Domain"):
        if c not in df.columns:
            raise ValueError(f"PhiUSIIL file is missing column '{c}'")
    lab = _numeric_labels(df["label"], "label")
    work = pd.DataFrame({"url": df["URL"].astype(str), "domain": df["Domain"].astype(str).str.lower().str.replace(r"^www\.", "", regex=True),
                         "is_phishing": 1 - lab.to_numpy()})                  # in this dataset label 1 = LEGITIMATE (UCI documentation)
    work = work[work["url"].str.len() > 3]
    work, dup = drop_exact_duplicates(work, ["url"])
    if max_rows and len(work) > max_rows:
        work = work.sample(max_rows, random_state=SEED).reset_index(drop=True)
        dup["subsampled_to"] = int(max_rows)
    return TaskSpec(
        model_name="url_phishing", task="ScamWatch: phishing vs legitimate URL (text of the address only)", dataset={**dataset, "rows_raw": int(len(df))},
        X=work[["url"]].reset_index(drop=True), y=work["is_phishing"].rename("is_phishing").reset_index(drop=True), input_features=["url"],
        feature_types={"url": "string"}, preprocessor=_url_host_pre if host_only else _url_pre,
        candidates=[c for c in candidates_default(fast) if c.name != "random_forest"],
        target_definition="is_phishing = 1 means the URL was labelled phishing by the dataset authors (their label 1 = legitimate is inverted here); 0 = legitimate",
        preprocessing_description=(f"{len(HOST_FEATURE_NAMES)} features of the canonical host name only (length, subdomains, digits, hyphens, entropy, longest label, top-level domain); "
                                   "scheme, a leading www, port, path, query and trailing slash are ignored; standardised with training-partition statistics only." if host_only else
                                   f"{len(URL_FEATURE_NAMES)} lexical features are computed from the URL string itself (lengths, character counts, host structure, "
                                   "keywords, entropy), then standardised with training-partition statistics only."),
        excluded_features=[{"name": "all page-content columns (LineOfCode, HasTitle, NoOfJS, ...)", "reason": "They require fetching the page; ScamWatch never opens a submitted link."},
                           {"name": "URLSimilarityIndex, CharContinuationRate, TLDLegitimateProb, URLCharProb", "reason": "Computed by the dataset authors from dataset-wide statistics: not reproducible for a single new URL."},
                           {"name": "FILENAME, Domain, Title", "reason": "Identifiers / content. Domain is used only to keep each site on one side of the split."}]
        + ([{"name": "scheme, www prefix, port, path, query, trailing slash, keywords", "reason": "In this dataset every legitimate address is https://www.<domain> with no path, so these cues "
            "separate the classes by how the lists were built. A model using them flags ordinary legitimate links after a cosmetic change."}] if host_only else []),
        derived_features=[{"name": n, "from": "url"} for n in (HOST_FEATURE_NAMES if host_only else URL_FEATURE_NAMES[:6])] + ([] if host_only else [{"name": "... and the rest of the lexical set", "from": "url"}]),
        cleaning={**dup, "feature_set": feature_set}, groups=work["domain"].to_numpy(), min_pr_auc=0.8 if host_only else 0.85, is_fixture=is_fixture, max_fpr=0.01 if host_only else None,
        split_override_note="Grouped by web domain so the same site never appears in both training and test.",
        source_note="PhiUSIIL Phishing URL dataset (UCI #967), CC BY 4.0.",
        limitations=["URL text only: a clean-looking address on a compromised site is invisible to this model. A low score is NOT evidence that a site is safe.",
                     "In this dataset most legitimate URLs are bare site roots while phishing URLs often have paths: part of the apparent accuracy comes from that collection artefact and will not carry over to real links.",
                     "Phishing changes quickly; a model trained on a 2024 snapshot ages. Treat it as one signal alongside blocklists."])


def load_creditcard(root: Path = EXTERNAL_DIR, fast: bool = False) -> TaskSpec:
    path, meta = verified_file("creditcard-openml", "creditcard_openml.parquet", root)
    return creditcard_task(pd.read_parquet(path), meta, fast)


def load_paysim(root: Path = EXTERNAL_DIR, fast: bool = False) -> TaskSpec:
    manifest = load_manifest("paysim", root)           # raises DatasetUnavailable with the exact download command
    csv = next((f["file"] for f in manifest["files"] if f["file"].lower().endswith(".csv")), None)
    if csv is None:
        raise DatasetUnavailable("The paysim download contains no CSV file.")
    path, meta = verified_file("paysim", csv, root)
    return paysim_task(pd.read_csv(path), meta, fast)


def load_phiusiil(root: Path = EXTERNAL_DIR, fast: bool = False, max_rows: int | None = None, feature_set: str = "host") -> TaskSpec:
    path, meta = verified_file("phiusiil", "PhiUSIIL_Phishing_URL_Dataset.csv", root)
    return phiusiil_task(pd.read_csv(path, usecols=["URL", "label", "Domain"]), meta, fast, max_rows=max_rows, feature_set=feature_set)


LOADERS = {"creditcard-openml": load_creditcard, "paysim": load_paysim, "phiusiil": load_phiusiil}
