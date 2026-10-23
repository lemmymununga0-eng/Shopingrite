"""ScamWatch phishing-URL experiments for the paper (PhiUSIIL, URL-text features only, domain-grouped split). From the repository root:

    python research/phishing_experiments.py benchmark    # 4 models, one protocol, bootstrap CIs, paired tests
    python research/phishing_experiments.py ablation     # which feature groups carry the accuracy
    python research/phishing_experiments.py controlled   # a subset where the dataset's obvious shortcuts are neutralised
    python research/phishing_experiments.py perturbation  # change one cue of held-out addresses and watch the model
    python research/phishing_experiments.py host_model   # the replacement model built from the host name only, with its robustness checks
    python research/phishing_experiments.py spot_checks  # fixed list of 12 addresses: original model versus the registry's host-name model
    python research/phishing_experiments.py score_spread  # share of held-out addresses with an extreme calibrated score
    python research/phishing_experiments.py importance   # coefficients and permutation importance of the logistic model
    python research/phishing_experiments.py all

Needs:  python backend/scripts/fetch_datasets.py get phiusiil --accept-licence
"""
import argparse
import dataclasses
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from _common import (RESULTS, SCRATCH, SEED, Timer, confusion_extras, environment, load, mcnemar_exact, save,  # noqa: E402
                     stratified_bootstrap)
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from app.ml import datasets as ds  # noqa: E402
from app.ml.framework import group_split, train_task  # noqa: E402

FAMILIES = ["logistic_regression", "random_forest", "hist_gradient_boosting"]
PRETTY = {"logistic_regression": "Logistic regression", "random_forest": "Random forest", "hist_gradient_boosting": "Gradient boosting (HistGB)"}


def spec(feature_set="lexical"):
    return ds.LOADERS["phiusiil"](ds.EXTERNAL_DIR, fast=False, feature_set=feature_set)


def candidates():
    base = {c.name: c for c in ds.candidates_default(False)}
    base["random_forest"] = dataclasses.replace(base["random_forest"], params=[{"min_samples_leaf": 2, "max_depth": None}])   # one setting: keeps the run affordable
    return base


def metrics_at(y, p, thr) -> dict:
    y = np.asarray(y).astype(int)
    pred = (np.asarray(p) >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    out = {"threshold": float(thr), "precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
           "accuracy": (tp + tn) / len(y), "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
           "fpr": fp / (fp + tn) if fp + tn else None}
    if len(set(y.tolist())) == 2:
        out["pr_auc"], out["roc_auc"] = float(average_precision_score(y, p)), float(roc_auc_score(y, p))
    out.update(confusion_extras(out["confusion_matrix"]))
    return out


def split_arrays(s):
    y = s.y.reset_index(drop=True).astype(int)
    sp = group_split(y, s.groups, seed=SEED)
    return sp, y


# ------------------------------------------------------------------------------------------------------------------ benchmark
def benchmark():
    s, tm = spec(), Timer()
    cands = candidates()
    res = {"environment": environment(), "dataset": s.dataset, "cleaning": s.cleaning, "models": {}, "split_seed": SEED}
    scores, y_test = {}, None
    for fam in FAMILIES:
        print(f"\n=== {fam}", flush=True)
        s1 = dataclasses.replace(s, candidates=[cands[fam]])
        r = train_task(s1, split_method="group", folds=4, seed=SEED)
        m = r.metadata
        y_test = r.test_y
        scores[fam] = r.test_proba
        mt = m["metrics"]
        mt.update(confusion_extras(mt["confusion_matrix"]))
        res["models"][fam] = {"label": PRETTY[fam], "selected": m["selected"], "cv_pr_auc": max(c["cv_pr_auc"] for c in m["candidates"]), "cv_grid": m["candidates"],
                              "threshold": m["threshold"], "test": {k: v for k, v in mt.items() if k not in ("classification_report", "reliability_calibrated")},
                              "reliability_calibrated": mt["reliability_calibrated"], "calibration": m["calibration"], "split": m["split"], "seconds": tm.lap()}
        if fam == "logistic_regression":
            joblib.dump(r.pipeline, SCRATCH / "phish_lr_model.joblib")
        print(f"  test PR-AUC {mt['pr_auc']:.4f} precision {mt['precision']:.4f} recall {mt['recall']:.4f}", flush=True)
    prev = float(np.mean(y_test))
    res["dummy"] = {"label": "Dummy (training prior)", "pr_auc": prev, "roc_auc": 0.5, "accuracy": 1 - prev, "precision": 0.0, "recall": 0.0, "f1": 0.0, "mcc": 0.0}
    np.savez_compressed(SCRATCH / "phish_scores.npz", y=y_test, **scores)
    thr = {f: res["models"][f]["threshold"] for f in FAMILIES}
    print("\nbootstrap (B=1000) ...", flush=True)
    res["bootstrap"] = stratified_bootstrap(y_test, scores, thr, B=1000)
    preds = {f: (scores[f] >= thr[f]).astype(int) for f in FAMILIES}
    res["mcnemar"] = {f"{a} vs {b}": mcnemar_exact(y_test, preds[a], preds[b]) for i, a in enumerate(FAMILIES) for b in FAMILIES[i + 1:]}
    save("phishing_benchmark", res)


# ------------------------------------------------------------------------------------------------------------------ ablation
HOST = ["host_len", "n_subdomains", "host_is_ip", "has_punycode", "host_digit_ratio", "host_hyphens", "host_entropy", "longest_label", "tld_len", "tld_common"]
PATHQ = ["path_len", "query_len", "path_depth", "n_equals", "n_qmark", "n_amp", "n_percent", "has_double_slash_in_path"]
PROTO = ["is_https", "has_port", "has_www"]


def features_matrix(s):
    cache = SCRATCH / "phish_features.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    F = ds._url_features(s.X)
    F.to_parquet(cache)
    return F


def fit_lr(Xtr, ytr, Xte, C=1.0):
    sc = StandardScaler().fit(Xtr)
    clf = LogisticRegression(class_weight="balanced", C=C, max_iter=1000).fit(sc.transform(Xtr), ytr)
    return clf.predict_proba(sc.transform(Xte))[:, 1], clf, sc


def ablation():
    s = spec()
    F = features_matrix(s)
    sp, y = split_arrays(s)
    allf = list(F.columns)
    sets = {
        "All 31 URL-text features": allf,
        "Without protocol and prefix features (is_https, has_port, has_www)": [f for f in allf if f not in PROTO],
        "Host-name features only": HOST,
        "Path and query features only": PATHQ,
        "URL length only": ["url_len"],
        "is_https only": ["is_https"],
        "has_www only": ["has_www"],
        "is_https + URL length": ["is_https", "url_len"],
        "Three collection cues (is_https, has_www, path_depth)": ["is_https", "has_www", "path_depth"],
    }
    rows = []
    Xtr, ytr, Xte, yte = F.iloc[sp.train_idx], y.iloc[sp.train_idx], F.iloc[sp.test_idx], y.iloc[sp.test_idx]
    for name, cols in sets.items():
        p, _, _ = fit_lr(Xtr[cols], ytr, Xte[cols])
        m = metrics_at(yte, p, 0.5)
        rows.append({"features": name, "n_features": len(cols), **{k: m[k] for k in ("pr_auc", "roc_auc", "precision", "recall", "f1", "mcc", "accuracy")}})
        print(f"{name}: PR-AUC {m['pr_auc']:.4f} F1 {m['f1']:.4f} recall {m['recall']:.3f}", flush=True)
    save("phishing_ablation", {"environment": environment(), "model": "logistic regression (class-weighted, C=1), threshold 0.5", "rows": rows,
                               "split": {"train_rows": int(len(ytr)), "test_rows": int(len(yte)), "test_phishing": int(yte.sum())}})


# ------------------------------------------------------------------------------------------------------------------ controlled
def url_parts(u: str):
    p = urlsplit(u if "://" in u else "http://" + u)
    return p.scheme, p.path or "", p.query or "", p.fragment or ""


def controlled():
    s = spec()
    F = features_matrix(s)
    sp, y = split_arrays(s)
    parts = [url_parts(u) for u in s.X["url"]]
    scheme = np.array([a for a, _, _, _ in parts])
    bare = np.array([(b in ("", "/")) and not c and not d for _, b, c, d in parts])
    https = scheme == "https"
    www = F["has_www"].to_numpy() == 1
    nopath = np.array([(b == "") and not c and not d for _, b, c, d in parts])           # no path at all, so no trailing slash either
    yv = y.to_numpy()
    masks = {"all rows": np.ones(len(y), bool), "bare site root (no path or query)": bare, "HTTPS": https, "www prefix": www, "no trailing slash or path": nopath,
             "bare HTTPS site root": bare & https, "exact legitimate template (https, www, no path)": https & www & nopath}
    out = {"environment": environment(), "counts": {n: {"legitimate": int(((yv == 0) & m).sum()), "phishing": int(((yv == 1) & m).sum())} for n, m in masks.items()}}
    out["share_of_class"] = {n: {"legitimate": float(m[yv == 0].mean()), "phishing": float(m[yv == 1].mean())} for n, m in masks.items()}
    out["mean_url_length"] = {"legitimate": float(F["url_len"][yv == 0].mean()), "phishing": float(F["url_len"][yv == 1].mean())}
    model = joblib.load(SCRATCH / "phish_lr_model.joblib")
    bench = load("phishing_benchmark")
    thr = bench["models"]["logistic_regression"]["threshold"]
    te, tr = np.asarray(sp.test_idx), np.asarray(sp.train_idx)
    out["subsets"] = {}
    for name in ("bare HTTPS site root", "exact legitimate template (https, www, no path)"):
        sub = masks[name]
        te_sub, tr_sub = te[sub[te]], tr[sub[tr]]
        rec = {"test_rows": int(len(te_sub)), "test_phishing": int(yv[te_sub].sum()), "train_rows": int(len(tr_sub)), "train_phishing": int(yv[tr_sub].sum())}
        p_sub = model.predict_proba(s.X.iloc[te_sub])[:, 1]
        rec["production_model"] = metrics_at(yv[te_sub], p_sub, thr)
        Xtr, Xte, ytr, yte = F.iloc[tr_sub], F.iloc[te_sub], yv[tr_sub], yv[te_sub]
        p_lr, _, _ = fit_lr(Xtr, ytr, Xte)
        rec["retrained_logistic_regression"] = metrics_at(yte, p_lr, 0.5)
        no_www = [c for c in F.columns if c not in ("has_www",)]
        p_nw, _, _ = fit_lr(Xtr[no_www], ytr, Xte[no_www])
        rec["retrained_without_www_feature"] = metrics_at(yte, p_nw, 0.5)
        p_host, _, _ = fit_lr(Xtr[HOST], ytr, Xte[HOST])
        rec["host_features_only"] = metrics_at(yte, p_host, 0.5)
        out["subsets"][name] = rec
        print(name, {k: round(v["pr_auc"], 3) for k, v in rec.items() if isinstance(v, dict) and "pr_auc" in v}, "test phishing", rec["test_phishing"], flush=True)
    save("phishing_controlled", out)


# ------------------------------------------------------------------------------------------------------------------ perturbation
def perturbation():
    """Counterfactual check: change one cue of held-out addresses and see how the production model reacts."""
    from urllib.parse import urlunsplit
    s = spec()
    sp, y = split_arrays(s)
    model = joblib.load(SCRATCH / "phish_lr_model.joblib")
    thr = load("phishing_benchmark")["models"]["logistic_regression"]["threshold"]
    te = np.asarray(sp.test_idx)
    urls, yv = s.X["url"].iloc[te].reset_index(drop=True), y.iloc[te].reset_index(drop=True).to_numpy()

    def parts(u):
        p = urlsplit(u if "://" in u else "http://" + u)
        return p.scheme, p.netloc, p.path, p.query, p.fragment

    def rebuild(sc, nl, pa, q):
        return urlunsplit((sc, nl, pa, q, ""))

    def strip_www(u):
        sc, nl, pa, q, _ = parts(u)
        return rebuild(sc, nl[4:] if nl.lower().startswith("www.") else nl, pa, q)

    def add_www(u):
        sc, nl, pa, q, _ = parts(u)
        return rebuild(sc, nl if nl.lower().startswith("www.") else "www." + nl, pa, q)

    def to_http(u):
        sc, nl, pa, q, _ = parts(u)
        return rebuild("http", nl, pa, q)

    def to_https(u):
        sc, nl, pa, q, _ = parts(u)
        return rebuild("https", nl, pa, q)

    def add_path(u):
        sc, nl, pa, q, _ = parts(u)
        return rebuild(sc, nl, pa if pa not in ("", "/") else "/products/index.html", q)

    def add_slash(u):
        sc, nl, pa, q, _ = parts(u)
        return rebuild(sc, nl, pa if pa not in ("",) else "/", q)

    def drop_slash(u):
        sc, nl, pa, q, _ = parts(u)
        return rebuild(sc, nl, "" if pa == "/" and not q else pa, q)

    def template(u):
        sc, nl, _, _, _ = parts(u)
        host = nl[4:] if nl.lower().startswith("www.") else nl
        return rebuild("https", "www." + host, "", "")

    def flagged(series):
        return (model.predict_proba(pd.DataFrame({"url": series}))[:, 1] >= thr)

    out = {"environment": environment(), "threshold": thr, "legitimate": {}, "phishing": {}}
    leg = urls[yv == 0]
    base = flagged(leg)
    out["legitimate"]["as released"] = {"flagged_share": float(base.mean()), "n": int(len(leg))}
    for name, fn in (("remove the www prefix", strip_www), ("use http instead of https", to_http), ("add a trailing slash", add_slash), ("add a path", add_path)):
        out["legitimate"][name] = {"flagged_share": float(flagged(leg.map(fn)).mean()), "n": int(len(leg))}
    ph = urls[yv == 1]
    out["phishing"]["as released"] = {"flagged_share": float(flagged(ph).mean()), "n": int(len(ph))}
    for name, fn in (("add a www prefix", add_www), ("use https instead of http", to_https), ("drop a lone trailing slash", drop_slash), ("rewrite as https://www.<host> (legitimate template)", template)):
        out["phishing"][name] = {"flagged_share": float(flagged(ph.map(fn)).mean()), "n": int(len(ph))}
    save("phishing_perturbation", out)
    for side in ("legitimate", "phishing"):
        for k, v in out[side].items():
            print(f"{side:11s} {k:45s} flagged {v['flagged_share']:.4f}", flush=True)


# ------------------------------------------------------------------------------------------------------------------ host-name model (the fix)
def cosmetic_shares(score, thr, legit, phish):
    out = {"legitimate": {"as released": float((np.asarray(score(legit)) >= thr).mean())}, "phishing": {"as released": float((np.asarray(score(phish)) >= thr).mean())}}
    for n, fn in ds.COSMETIC_CHANGES_LEGIT.items():
        out["legitimate"][n] = float((np.asarray(score([fn(u) for u in legit])) >= thr).mean())
    out["phishing"]["rewrite as https://www.<host>"] = float((np.asarray(score([ds._as_legit_template(u) for u in phish])) >= thr).mean())
    return out


def host_model():
    """Same protocol and split, but only the canonical host name is used. Reports accuracy and the invariance checks."""
    from app.ml import train as T
    s = spec("host")
    cands = candidates()
    sp, y = split_arrays(s)
    urls = s.X["url"].reset_index(drop=True)
    te = np.asarray(sp.test_idx)
    yt = y.to_numpy()[te]
    legit, phish = urls.iloc[te][yt == 0].tolist(), urls.iloc[te][yt == 1].tolist()
    res = {"environment": environment(), "feature_set": "host", "features": ds.HOST_FEATURE_NAMES, "models": {}}
    scores = {}
    for fam in ("logistic_regression", "hist_gradient_boosting"):
        print(f"=== host-only {fam}", flush=True)
        s1 = dataclasses.replace(s, candidates=[cands[fam]])
        r = train_task(s1, split_method="group", folds=4, seed=SEED)
        m = r.metadata
        T.url_gate(s1, r, m, log=lambda *a: None)
        mt = m["metrics"]
        mt.update(confusion_extras(mt["confusion_matrix"]))
        thr = m["threshold"]
        score = lambda u, r=r: r.pipeline.predict_proba(pd.DataFrame({"url": u}))[:, 1]       # noqa: E731
        res["models"][fam] = {"label": PRETTY[fam], "selected": m["selected"], "threshold": thr, "cv_pr_auc": max(c["cv_pr_auc"] for c in m["candidates"]),
                              "test": {k: v for k, v in mt.items() if k not in ("classification_report", "reliability_calibrated")},
                              "invariance_checks": [c for c in m["validation"]["checks"] if "addresses" in c["check"]],
                              "cosmetic_flagged_shares": cosmetic_shares(score, thr, legit, phish), "validation_passed": m["validation"]["passed"],
                              "failures": m["validation"]["failures"], "calibration": m["calibration"]}
        scores[fam] = r.test_proba
        y_test = r.test_y
        print(f"  test PR-AUC {mt['pr_auc']:.4f} precision {mt['precision']:.4f} recall {mt['recall']:.4f} fpr {mt['false_positive_rate']:.4f} gate passed {m['validation']['passed']}", flush=True)
    np.savez_compressed(SCRATCH / "phish_host_scores.npz", y=y_test, **scores)
    thr = {f: res["models"][f]["threshold"] for f in scores}
    res["bootstrap"] = stratified_bootstrap(y_test, scores, thr, B=1000)
    save("phishing_host_model", res)


# ------------------------------------------------------------------------------------------------------------------ spot checks
SPOT = [("legitimate-looking", "https://www.example.co.zm"), ("legitimate-looking", "https://example.co.zm"), ("legitimate-looking", "https://google.com"),
        ("legitimate-looking", "https://mail.google.com/mail/u/0/"), ("legitimate-looking", "https://github.com/lemmymununga0-eng/Shopingrite"),
        ("hypothetical small business", "https://my-small-grocery-lusaka-fresh-produce.com"),
        ("phishing in the data", "https://doncov.line.pm/"), ("same host, legitimate format", "https://www.doncov.line.pm"),
        ("phishing in the data", "https://sparkasse-auth.com/"), ("same host, legitimate format", "https://www.sparkasse-auth.com"),
        ("phishing in the data", "https://att-107489-107815yoomimi.weeblysite.com/"), ("same host, legitimate format", "https://www.att-107489-107815yoomimi.weeblysite.com")]


def spot_checks():
    """Verdicts of the original (31-feature) model and of the registry's current host-name model on a fixed list of addresses."""
    from app.ml import registry
    from app.ml.service import ModelService
    lex = joblib.load(SCRATCH / "phish_lr_model.joblib")
    thr_lex = load("phishing_benchmark")["models"]["logistic_regression"]["threshold"]
    svc = ModelService(registry.ARTIFACT_ROOT)
    svc.load_all()
    urls = [u for _, u in SPOT]
    p_lex = lex.predict_proba(pd.DataFrame({"url": urls}))[:, 1]
    rows = []
    for (kind, u), pl in zip(SPOT, p_lex):
        r = svc.predict("url_phishing", {"url": u})
        rows.append({"kind": kind, "url": u, "original_probability": float(pl), "original_flagged": bool(pl >= thr_lex),
                     "host_probability": r.get("probability"), "host_flagged": r.get("flagged")})
    st = svc.status("url_phishing")
    save("phishing_spot_checks", {"environment": environment(), "original_threshold": thr_lex, "host_model_version": st.get("version"), "host_model_threshold": st.get("threshold"),
                                  "host_model_experimental": st.get("experimental"), "rows": rows})
    for r in rows:
        print(f"{r['kind']:30s} original {r['original_probability']:.3f} {'FLAG' if r['original_flagged'] else '    '} | host {r['host_probability']:.3f} {'FLAG' if r['host_flagged'] else '    '}  {r['url']}")


def score_spread():
    """How many held-out addresses receive an extreme calibrated score. Explains why the expected calibration error of the original models is
    tiny although the middle of their reliability diagram is poor: almost no address scores in the middle."""
    z = np.load(SCRATCH / "phish_scores.npz")
    out = {"environment": environment(), "n": int(len(z["y"])), "models": {}}
    for fam in FAMILIES:
        p = z[fam]
        out["models"][fam] = {"share_below_0_05_or_above_0_95": float(((p < 0.05) | (p > 0.95)).mean()), "share_between_0_2_and_0_8": float(((p >= 0.2) & (p <= 0.8)).mean())}
    save("phishing_score_spread", out)
    for fam, v in out["models"].items():
        print(f"{fam:26s} extreme {100 * v['share_below_0_05_or_above_0_95']:.1f}%  middle {100 * v['share_between_0_2_and_0_8']:.2f}%")


# ------------------------------------------------------------------------------------------------------------------ importance
def importance():
    s = spec()
    model = joblib.load(SCRATCH / "phish_lr_model.joblib")
    sp, y = split_arrays(s)
    pipe = model.base
    clf = pipe.named_steps["clf"]
    coef = sorted(({"feature": f, "standardised_coefficient": float(c)} for f, c in zip(ds.URL_FEATURE_NAMES, clf.coef_[0])), key=lambda t: -abs(t["standardised_coefficient"]))
    Xte, yte = s.X.iloc[sp.test_idx].reset_index(drop=True), y.iloc[sp.test_idx].reset_index(drop=True)
    rng = np.random.default_rng(SEED)
    sub = rng.choice(len(yte), 8000, replace=False)
    # permutation on the engineered matrix, one feature at a time (own loop: no estimator interface needed)
    Fte = ds._url_features(Xte.iloc[sub].reset_index(drop=True))
    scaler, lr = pipe.named_steps["pre"].named_steps["scale"], clf
    ys = yte.iloc[sub].reset_index(drop=True).to_numpy()
    score = lambda F: float(average_precision_score(ys, lr.predict_proba(scaler.transform(F))[:, 1]))     # noqa: E731
    base = score(Fte)
    rng2 = np.random.default_rng(SEED)
    perm = []
    for col in Fte.columns:
        drops = []
        for _ in range(5):
            F2 = Fte.copy()
            F2[col] = rng2.permutation(F2[col].to_numpy())
            drops.append(base - score(F2))
        perm.append({"feature": col, "mean_drop_in_pr_auc": float(np.mean(drops)), "sd": float(np.std(drops))})
    perm.sort(key=lambda t: -t["mean_drop_in_pr_auc"])
    save("phishing_importance", {"environment": environment(), "coefficients": coef, "permutation": perm,
                                 "note": "permutation importance on 8000 random test rows, 5 repeats, metric = PR-AUC drop"})


STEPS = {"benchmark": benchmark, "ablation": ablation, "controlled": controlled, "perturbation": perturbation, "host_model": host_model, "spot_checks": spot_checks, "score_spread": score_spread,
         "importance": importance}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=[*STEPS, "all"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for name in (STEPS if a.step == "all" else [a.step]):
        if (RESULTS / f"phishing_{name}.json").exists() and not a.force and a.step == "all":
            print(f"skip {name} (exists)")
            continue
        t0 = time.time()
        STEPS[name]()
        print(f"[{name}] done in {time.time() - t0:.0f}s", flush=True)
