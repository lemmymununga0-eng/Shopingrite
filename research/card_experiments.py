"""Credit-card fraud experiments for the paper (public ULB data, OpenML mirror). Run from the repository root:

    python research/card_experiments.py benchmark     # 4 models, one protocol, bootstrap CIs, paired tests, calibration, chronological check
    python research/card_experiments.py protocol      # how much a careless evaluation protocol inflates the numbers
    python research/card_experiments.py seeds         # variability across 5 random splits
    python research/card_experiments.py curve         # learning curve (train vs cross-validated PR-AUC)
    python research/card_experiments.py importance    # permutation + impurity importance of the random forest
    python research/card_experiments.py latency       # scoring latency of the promoted registry models
    python research/card_experiments.py all

Needs the dataset downloaded and verified:  python backend/scripts/fetch_datasets.py get creditcard-openml --accept-licence
Writes research/results/card_*.json (committed) and large arrays to research/results/_scratch/ (ignored).
"""
import argparse
import dataclasses
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from _common import (RESULTS, SCRATCH, SEED, Timer, confusion_extras, environment, load, mcnemar_exact, save,  # noqa: E402
                     stratified_bootstrap)
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score  # noqa: E402

from app.ml import datasets as ds  # noqa: E402
from app.ml.framework import _pipe, chronological_robustness, stratified_split, train_task  # noqa: E402

FAMILIES = ["logistic_regression", "random_forest", "hist_gradient_boosting"]
PRETTY = {"logistic_regression": "Logistic regression", "random_forest": "Random forest", "hist_gradient_boosting": "Gradient boosting (HistGB)"}


def spec():
    return ds.LOADERS["creditcard-openml"](ds.EXTERNAL_DIR, fast=False)


def split_of(s):
    X, y = s.X.reset_index(drop=True), s.y.reset_index(drop=True).astype(int)
    sp = stratified_split(y, seed=SEED)
    return X.iloc[sp.train_idx].reset_index(drop=True), y.iloc[sp.train_idx].reset_index(drop=True), \
        X.iloc[sp.test_idx].reset_index(drop=True), y.iloc[sp.test_idx].reset_index(drop=True)


def metrics_at(y, p, thr) -> dict:
    y = np.asarray(y).astype(int)
    pred = (np.asarray(p) >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    out = {"threshold": float(thr), "precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
           "accuracy": (tp + tn) / len(y), "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
           "pr_auc": float(average_precision_score(y, p)), "roc_auc": float(roc_auc_score(y, p))}
    out.update(confusion_extras(out["confusion_matrix"]))
    return out


# ------------------------------------------------------------------------------------------------------------------ benchmark
def benchmark():
    s, tm = spec(), Timer()
    cands = {c.name: c for c in s.candidates}
    res = {"environment": environment(), "dataset": s.dataset, "cleaning": s.cleaning, "models": {}, "split_seed": SEED}
    scores, y_test = {}, None
    for fam in FAMILIES:
        print(f"\n=== {fam}", flush=True)
        s1 = dataclasses.replace(s, candidates=[cands[fam]])
        r = train_task(s1, split_method="stratified", folds=4, seed=SEED)
        m = r.metadata
        y_test = r.test_y
        scores[fam] = r.test_proba
        chron = chronological_robustness(s1, m["selected"], m["threshold"])
        mt = m["metrics"]
        mt.update(confusion_extras(mt["confusion_matrix"]))
        res["models"][fam] = {"label": PRETTY[fam], "selected": m["selected"], "cv_pr_auc": m["candidates"][0]["cv_pr_auc"] if len(m["candidates"]) == 1 else
                              max(c["cv_pr_auc"] for c in m["candidates"]), "cv_grid": m["candidates"], "threshold": m["threshold"],
                              "threshold_info": m["threshold_info"], "test": {k: v for k, v in mt.items() if k not in ("classification_report", "reliability_calibrated")},
                              "reliability_calibrated": mt["reliability_calibrated"], "calibration": m["calibration"], "chronological": chron,
                              "split": m["split"], "validation_passed": m["validation"]["passed"], "seconds": tm.lap()}
        if fam == "random_forest":
            joblib.dump(r.pipeline, SCRATCH / "rf_model.joblib")
        print(f"  test PR-AUC {mt['pr_auc']:.4f}  precision {mt['precision']:.3f}  recall {mt['recall']:.3f}", flush=True)
    prev = float(np.mean(y_test))
    res["dummy"] = {"label": "Dummy (training prior)", "pr_auc": prev, "roc_auc": 0.5, "accuracy": 1 - prev, "precision": 0.0, "recall": 0.0, "f1": 0.0, "mcc": 0.0}
    np.savez_compressed(SCRATCH / "card_scores.npz", y=y_test, **scores)

    thr = {f: res["models"][f]["threshold"] for f in FAMILIES}
    print("\nbootstrap (B=1000) ...", flush=True)
    res["bootstrap"] = stratified_bootstrap(y_test, scores, thr, B=1000)
    preds = {f: (scores[f] >= thr[f]).astype(int) for f in FAMILIES}
    res["mcnemar"] = {f"{a} vs {b}": mcnemar_exact(y_test, preds[a], preds[b]) for i, a in enumerate(FAMILIES) for b in FAMILIES[i + 1:]}
    res["seconds_total"] = tm.lap()
    save("card_benchmark", res)


# ------------------------------------------------------------------------------------------------------------------ protocol
def protocol():
    s = spec()
    bench = load("card_benchmark")
    params = bench["models"]["random_forest"]["selected"]["params"]
    cand = {c.name: c for c in s.candidates}["random_forest"]
    X, y = s.X.reset_index(drop=True), s.y.reset_index(drop=True).astype(int)
    rows = []

    def fit_eval(label, Xtr, ytr, Xte, yte, note):
        pipe = _pipe(s, cand.make(**params)).fit(Xtr, ytr)
        p = pipe.predict_proba(Xte)[:, list(pipe.classes_).index(1)]
        m = metrics_at(yte, p, 0.5)
        best = None
        pr, rc, th = precision_recall_curve(yte, p)
        f1 = np.where(pr + rc > 0, 2 * pr * rc / (pr + rc), 0)[:-1]
        if len(th):
            i = int(np.argmax(f1))
            best = {"threshold": float(th[i]), "f1": float(f1[i]), "precision": float(pr[i]), "recall": float(rc[i])}
        rows.append({"variant": label, "note": note, "train_rows": int(len(ytr)), "test_rows": int(len(yte)), "test_fraud": int(yte.sum()),
                     **{k: m[k] for k in ("pr_auc", "roc_auc", "precision", "recall", "f1", "mcc")}, "confusion_matrix": m["confusion_matrix"],
                     "best_threshold_on_test": best})
        print(f"{label}: PR-AUC {m['pr_auc']:.3f} precision {m['precision']:.3f} recall {m['recall']:.3f} F1 {m['f1']:.3f}", flush=True)

    sp = stratified_split(y, seed=SEED)
    Xtr, ytr = X.iloc[sp.train_idx].reset_index(drop=True), y.iloc[sp.train_idx].reset_index(drop=True)
    Xte, yte = X.iloc[sp.test_idx].reset_index(drop=True), y.iloc[sp.test_idx].reset_index(drop=True)
    fit_eval("A. Correct protocol (deduplicated, split first)", Xtr, ytr, Xte, yte, "the protocol used in this paper")

    # B. oversample the fraud class BEFORE splitting: copies of the same fraud row land on both sides of the split
    fraud_idx = np.flatnonzero(y == 1)
    rep = np.concatenate([np.arange(len(y))] + [fraud_idx] * 19)
    Xo, yo = X.iloc[rep].reset_index(drop=True), y.iloc[rep].reset_index(drop=True)
    so = stratified_split(yo, seed=SEED)
    fit_eval("B. Oversample fraud before splitting (x20)", Xo.iloc[so.train_idx].reset_index(drop=True), yo.iloc[so.train_idx].reset_index(drop=True),
             Xo.iloc[so.test_idx].reset_index(drop=True), yo.iloc[so.test_idx].reset_index(drop=True),
             "identical fraud rows appear in training and test (data leakage)")

    # D. keep the exact duplicate rows that the cleaned data drops
    path, _ = ds.verified_file("creditcard-openml", "creditcard_openml.parquet")
    raw = pd.read_parquet(path)
    cols = list(X.columns)
    rx = raw[cols].apply(pd.to_numeric, errors="coerce")
    ry = ds._numeric_labels(raw["Class"], "Class").reset_index(drop=True)
    ok = rx.notna().all(axis=1).to_numpy()
    rx, ry = rx[ok].reset_index(drop=True), ry[ok].reset_index(drop=True)
    sd_ = stratified_split(ry, seed=SEED)
    fit_eval("C. Keep exact duplicate rows", rx.iloc[sd_.train_idx].reset_index(drop=True), ry.iloc[sd_.train_idx].reset_index(drop=True),
             rx.iloc[sd_.test_idx].reset_index(drop=True), ry.iloc[sd_.test_idx].reset_index(drop=True), f"{len(raw) - len(X):,} duplicate rows kept")
    save("card_protocol", {"environment": environment(), "random_forest_params": params, "rows": rows,
                           "note": "All variants use the same random-forest settings. Precision, recall and F1 are at a fixed raw-score threshold of 0.5."})


# ------------------------------------------------------------------------------------------------------------------ seeds
def seeds():
    s = spec()
    bench = load("card_benchmark")
    cands = {c.name: c for c in s.candidates}
    out = {"environment": environment(), "seeds": [11, 22, 33, 44, 55], "models": {}}
    for fam in ("logistic_regression", "random_forest"):
        sel = bench["models"][fam]["selected"]["params"]
        single = dataclasses.replace(cands[fam], params=[sel])
        runs = []
        for seed in out["seeds"]:
            r = train_task(dataclasses.replace(s, candidates=[single]), split_method="stratified", folds=4, seed=seed, log=lambda *a: None)
            mt = r.metadata["metrics"]
            runs.append({"seed": seed, "pr_auc": mt["pr_auc"], "roc_auc": mt["roc_auc"], "precision": mt["precision"], "recall": mt["recall"], "f1": mt["f1"],
                         "fraud_in_test": mt["support_fraud"]})
            print(f"{fam} seed {seed}: PR-AUC {mt['pr_auc']:.3f} recall {mt['recall']:.3f} precision {mt['precision']:.3f}", flush=True)
        arr = {k: np.array([r[k] for r in runs]) for k in ("pr_auc", "roc_auc", "precision", "recall", "f1")}
        out["models"][fam] = {"label": PRETTY[fam], "params": sel, "runs": runs,
                              "summary": {k: {"mean": float(v.mean()), "sd": float(v.std(ddof=1)), "min": float(v.min()), "max": float(v.max())} for k, v in arr.items()}}
    save("card_seeds", out)


# ------------------------------------------------------------------------------------------------------------------ curve
def curve():
    from sklearn.model_selection import StratifiedKFold, learning_curve
    s = spec()
    bench = load("card_benchmark")
    params = bench["models"]["random_forest"]["selected"]["params"]
    cand = {c.name: c for c in s.candidates}["random_forest"]
    Xtr, ytr, _, _ = split_of(s)
    pipe = _pipe(s, cand.make(**params))
    sizes, tr, va = learning_curve(pipe, Xtr, ytr, train_sizes=[0.1, 0.25, 0.5, 0.75, 1.0], cv=StratifiedKFold(3, shuffle=True, random_state=SEED),
                                   scoring="average_precision", n_jobs=1, random_state=SEED)
    save("card_learning_curve", {"environment": environment(), "train_sizes": sizes, "train_pr_auc_mean": tr.mean(axis=1), "train_pr_auc_sd": tr.std(axis=1),
                                 "validation_pr_auc_mean": va.mean(axis=1), "validation_pr_auc_sd": va.std(axis=1), "cv_folds": 3,
                                 "note": "training partition only (the test partition is not used)"})


# ------------------------------------------------------------------------------------------------------------------ importance
def importance():
    from sklearn.inspection import permutation_importance
    s = spec()
    model = joblib.load(SCRATCH / "rf_model.joblib")
    Xtr, ytr, Xte, yte = split_of(s)
    rng = np.random.default_rng(SEED)
    pos, neg = np.flatnonzero(yte == 1), np.flatnonzero(yte == 0)
    sub = np.concatenate([pos, rng.choice(neg, 8000, replace=False)])
    Xs, ys = Xte.iloc[sub].reset_index(drop=True), yte.iloc[sub].reset_index(drop=True)
    r = permutation_importance(model.base, Xs, ys, scoring="average_precision", n_repeats=5, random_state=SEED, n_jobs=1)
    perm = sorted(({"feature": f, "mean_drop_in_pr_auc": float(m), "sd": float(d)} for f, m, d in zip(Xte.columns, r.importances_mean, r.importances_std)),
                  key=lambda t: -t["mean_drop_in_pr_auc"])
    feats = list(ds._cc_features(Xte.head(3)).columns)
    imp = model.base.named_steps["clf"].feature_importances_
    gini = sorted(({"feature": f, "importance": float(v)} for f, v in zip(feats, imp)), key=lambda t: -t["importance"])
    save("card_importance", {"environment": environment(), "permutation": perm, "impurity": gini,
                             "note": f"permutation importance on a stratified test subsample ({len(pos)} fraud + 8000 legitimate rows), 5 repeats, metric = PR-AUC drop"})


# ------------------------------------------------------------------------------------------------------------------ latency
def latency():
    from app.ml import registry
    from app.ml.service import ModelService
    svc = ModelService(registry.ARTIFACT_ROOT)
    svc.load_all()
    s = spec()
    _, _, Xte, _ = split_of(s)
    row = {k: float(v) for k, v in Xte.iloc[0].items()}
    out = {"environment": environment(), "models": {}}
    reqs = [("creditcard_pca", row), ("url_phishing", {"url": "http://secure-login-account.example.xyz/verify?id=12345"})]
    for name, feats in reqs:
        if not svc.result(name).ready:
            out["models"][name] = {"state": svc.result(name).state}
            continue
        for _ in range(20):
            svc.predict(name, feats)
        ts = []
        for _ in range(500):
            t = time.perf_counter()
            r = svc.predict(name, feats)
            ts.append((time.perf_counter() - t) * 1000)
        assert r["status"] == "ok", r
        a = np.array(ts)
        out["models"][name] = {"state": "ready", "n": 500, "p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)),
                               "p99_ms": float(np.percentile(a, 99)), "mean_ms": float(a.mean())}
    save("card_latency", out)


# ------------------------------------------------------------------------------------------------------------------ ties
def ties():
    s = spec()
    model = joblib.load(SCRATCH / "rf_model.joblib")
    _, _, Xte, yte = split_of(s)
    raw, cal = model.raw_score(Xte), model.predict_proba(Xte)[:, 1]
    out = {"environment": environment(), "model": "random forest (selected)", "test_rows": int(len(yte)), "fraud_rows": int(yte.sum())}
    for name, p in (("raw_score", raw), ("calibrated", cal)):
        out[name] = {"pr_auc": float(average_precision_score(yte, p)), "roc_auc": float(roc_auc_score(yte, p)), "distinct_values": int(len(np.unique(p)))}
    save("card_calibration_effect", out)


# ------------------------------------------------------------------------------------------------------------------ ranking
def ranking():
    """Where each model ranks the held-out frauds among the legitimate transactions (explains PR-AUC versus ROC-AUC)."""
    z = np.load(SCRATCH / "card_scores.npz")
    y = z["y"]
    out = {"environment": environment(), "fraud_rows": int((y == 1).sum()), "models": {}}
    for f in FAMILIES:
        p = z[f]
        neg = np.sort(p[y == 0])
        share_below = np.searchsorted(neg, p[y == 1], side="left") / len(neg)      # share of legitimate rows scored strictly lower
        pr, rc, _ = precision_recall_curve(y, p)
        out_extra = {"max_recall_at_precision_0_9": float(rc[pr >= 0.9].max()) if (pr >= 0.9).any() else 0.0, "max_recall_at_precision_0_5": float(rc[pr >= 0.5].max()) if (pr >= 0.5).any() else 0.0}
        out["models"][f] = {**out_extra, "label": PRETTY[f], "frauds_above_99_9pct_of_legit": int((share_below > 0.999).sum()),
                            "frauds_above_99pct_of_legit": int((share_below > 0.99).sum()), "frauds_above_90pct_of_legit": int((share_below > 0.9).sum()),
                            "frauds_below_median_legit": int((share_below < 0.5).sum()), "frauds_with_score_below_0_05": int((p[y == 1] < 0.05).sum())}
    save("card_ranking_profile", out)


STEPS = {"benchmark": benchmark, "protocol": protocol, "seeds": seeds, "curve": curve, "importance": importance, "latency": latency, "ties": ties, "ranking": ranking}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=[*STEPS, "all"])
    ap.add_argument("--force", action="store_true", help="recompute even if the result file exists")
    a = ap.parse_args()
    for name in (STEPS if a.step == "all" else [a.step]):
        out = RESULTS / f"card_{'learning_curve' if name == 'curve' else 'calibration_effect' if name == 'ties' else 'ranking_profile' if name == 'ranking' else name}.json"
        if out.exists() and not a.force and a.step == "all":
            print(f"skip {name} (exists)")
            continue
        t0 = time.time()
        STEPS[name]()
        print(f"[{name}] done in {time.time() - t0:.0f}s", flush=True)
