"""Shared, dataset-independent training machinery for the fraud and ScamWatch models.

Everything here is written to prevent the usual ways a fraud model fools its author:

  * SPLIT FIRST. The held-out test partition is carved out before anything is fitted. Preprocessing, model selection,
    calibration and the decision threshold all see the TRAINING partition only (the threshold and calibration use
    out-of-fold predictions on it). The test partition is used once, for the final numbers.
  * LEAKAGE. Adapters declare which columns are excluded and why; exact duplicate rows are removed before splitting so a
    row cannot sit in both partitions; when an entity/group column exists the split is by group.
  * IMBALANCE. Metrics that stay honest for rare fraud (precision, recall, PR-AUC, false-positive rate) are reported next to
    accuracy, never accuracy alone, and a do-nothing baseline is always trained for comparison.
  * HONESTY. Every number in the metadata is computed from real predictions. A candidate that fails the validation gate is
    saved but never promoted, so the last known-good model keeps serving.
"""
import json
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.dummy import DummyClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss, classification_report, confusion_matrix,
                             f1_score, fbeta_score, precision_recall_curve, precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import GroupShuffleSplit, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline

SEED = 42
TEST_SIZE = 0.2


# ----------------------------------------------------------------------------------------------------------- splitting
@dataclass
class Split:
    train_idx: np.ndarray
    test_idx: np.ndarray
    method: str
    note: str = ""


def stratified_split(y, test_size: float = TEST_SIZE, seed: int = SEED) -> Split:
    idx = np.arange(len(y))
    tr, te = train_test_split(idx, test_size=test_size, random_state=seed, stratify=np.asarray(y))
    return Split(np.sort(tr), np.sort(te), "stratified random 80/20")


def group_split(y, groups, test_size: float = TEST_SIZE, seed: int = SEED) -> Split:
    """No group (for example a web domain or an account) appears on both sides. Tries a few seeds so both classes are in both partitions."""
    y = np.asarray(y)
    for k in range(20):
        gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed + k)
        tr, te = next(gss.split(np.zeros(len(y)), y, np.asarray(groups)))
        if len(set(y[tr])) == 2 and len(set(y[te])) == 2:
            return Split(np.sort(tr), np.sort(te), "group-based 80/20 (no group on both sides)",
                         "Groups are kept whole, so the class ratio of the two partitions is only approximately equal.")
    raise ValueError("Could not make a group split with both classes on both sides.")


def chronological_split(order, test_size: float = TEST_SIZE) -> Split:
    """Oldest 80% train, newest 20% test: the realistic check that a model trained on the past works on the future."""
    idx = np.argsort(np.asarray(order), kind="stable")
    cut = int(round(len(idx) * (1 - test_size)))
    return Split(np.sort(idx[:cut]), np.sort(idx[cut:]), "chronological 80/20 (oldest train, newest test)")


def assert_no_overlap(split: Split, groups=None) -> None:
    if set(split.train_idx.tolist()) & set(split.test_idx.tolist()):
        raise AssertionError("Training and test partitions share rows.")
    if groups is not None:
        g = np.asarray(groups)
        if set(g[split.train_idx].tolist()) & set(g[split.test_idx].tolist()):
            raise AssertionError("Training and test partitions share groups.")


# --------------------------------------------------------------------------------------------------------- calibration
class CalibratedModel(BaseEstimator, ClassifierMixin):
    """A fitted pipeline plus an isotonic map from its raw score to an observed fraud frequency.

    The raw score of a class-weighted classifier is a RANK, not a probability. The calibrator is fitted on out-of-fold
    predictions of the training partition only, so `predict_proba` returns something that can be read as a probability."""

    def __init__(self, base=None, calibrator=None, input_features=None):
        self.base, self.calibrator, self.input_features = base, calibrator, input_features
        self.classes_ = np.array([0, 1])

    def raw_score(self, X) -> np.ndarray:
        return self.base.predict_proba(X)[:, list(self.base.classes_).index(1)]

    def predict_proba(self, X) -> np.ndarray:
        if self.input_features is not None:
            missing = [c for c in self.input_features if c not in X.columns]
            if missing:
                raise ValueError(f"Missing input features: {missing[:5]}")
            X = X[self.input_features]
        p = np.clip(self.calibrator.predict(self.raw_score(X)), 0.0, 1.0)
        return np.column_stack([1 - p, p])


def expected_calibration_error(y, p, bins: int = 10) -> float:
    """Average gap between predicted probability and observed fraud frequency, in equal-count bins (rare classes need these)."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    order = np.argsort(p)
    chunks = np.array_split(order, bins)
    return float(sum(len(c) / len(y) * abs(p[c].mean() - y[c].mean()) for c in chunks if len(c)))


def reliability_table(y, p, bins: int = 10) -> list[dict]:
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    out = []
    for c in np.array_split(np.argsort(p), bins):
        if len(c):
            out.append({"mean_predicted": round(float(p[c].mean()), 6), "observed_rate": round(float(y[c].mean()), 6), "count": int(len(c))})
    return out


# ------------------------------------------------------------------------------------------------------------- metrics
def full_metrics(y_true, proba, threshold: float) -> dict:
    """Everything the brief asks for, computed from real predictions on the given partition."""
    y = np.asarray(y_true).astype(int)
    p = np.asarray(proba, dtype=float)
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    neg, pos = int(tn + fp), int(tp + fn)
    out = {
        "threshold": float(threshold), "test_rows": int(len(y)), "support_legitimate": neg, "support_fraud": pos,
        "fraud_prevalence": float(y.mean()) if len(y) else None,
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)), "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)), "f2": float(fbeta_score(y, pred, beta=2, zero_division=0)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "false_positives": int(fp), "false_negatives": int(fn),
        "false_positive_rate": float(fp / neg) if neg else None, "false_negative_rate": float(fn / pos) if pos else None,
        "flagged_share": float(pred.mean()) if len(y) else None,
        "classification_report": classification_report(y, pred, labels=[0, 1], target_names=["legitimate", "fraud"], output_dict=True, zero_division=0),
        "brier": float(brier_score_loss(y, np.clip(p, 0, 1))) if len(y) else None,
        "calibration_error_ece": expected_calibration_error(y, p) if len(y) else None,
    }
    if len(set(y.tolist())) == 2:
        out["pr_auc"] = float(average_precision_score(y, p))
        out["roc_auc"] = float(roc_auc_score(y, p))
    else:
        out["pr_auc"] = out["roc_auc"] = None
        out["warning"] = "Only one class present: PR-AUC and ROC-AUC are not defined."
    if pos < 30:
        out["warning"] = (out.get("warning", "") + f" Only {pos} fraud rows in this partition: precision and recall are very unreliable.").strip()
    return out


def select_threshold(y, p, beta: float = 2.0) -> dict:
    """Pick the decision threshold on TRAINING-side (out-of-fold) predictions by maximising F-beta.

    Business objective: a missed fraud costs more than an unnecessary review, so recall is weighted `beta` times as much as
    precision (beta=2). The held-out test set plays no part in this choice."""
    y, p = np.asarray(y).astype(int), np.asarray(p, dtype=float)
    prec, rec, thr = precision_recall_curve(y, p)
    prec, rec = prec[:-1], rec[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        score = np.where((prec + rec) > 0, (1 + beta**2) * prec * rec / (beta**2 * prec + rec), 0.0)
    if not len(thr):
        return {"value": 0.5, "objective": f"F{beta:g}", "selected_on": "out-of-fold training predictions", "note": "no usable curve; default 0.5"}
    i = int(np.nanargmax(score))
    return {"value": float(thr[i]), "objective": f"maximise F{beta:g} (recall weighted {beta:g}x precision)",
            "selected_on": "out-of-fold predictions on the training partition only", "oof_precision": float(prec[i]), "oof_recall": float(rec[i])}


def select_threshold_at_fpr(y, p, max_fpr: float = 0.01) -> dict:
    """Highest-recall threshold whose false-positive rate on the given (training-side, out-of-fold) predictions stays at or below `max_fpr`.
    Used for signals that may only raise suspicion, where a bounded false-alarm rate matters more than catching everything."""
    from sklearn.metrics import roc_curve
    y, p = np.asarray(y).astype(int), np.asarray(p, dtype=float)
    fpr, tpr, thr = roc_curve(y, p)
    ok = np.flatnonzero(fpr <= max_fpr)
    i = int(ok[-1]) if len(ok) else 0
    t = float(thr[i]) if np.isfinite(thr[i]) else float(p.max()) + 1e-9
    pred = p >= t
    tp, fp = int(((pred == 1) & (y == 1)).sum()), int(((pred == 1) & (y == 0)).sum())
    return {"value": t, "objective": f"maximise recall with a false-positive rate of at most {max_fpr:g}", "selected_on": "out-of-fold predictions on the training partition only",
            "oof_precision": tp / (tp + fp) if tp + fp else 0.0, "oof_recall": float(tpr[i]), "oof_false_positive_rate": float(fpr[i])}


# ---------------------------------------------------------------------------------------------------- task description
@dataclass
class Candidate:
    name: str
    make: object                    # callable(**params) -> unfitted classifier
    params: list[dict]              # small grid, searched by cross-validation on the training partition only
    note: str = ""


@dataclass
class TaskSpec:
    model_name: str
    task: str
    dataset: dict                   # name, source, licence, licence_status, sha256, attribution, rows_raw
    X: pd.DataFrame                 # RAW input rows, columns == input_features (what the API will receive)
    y: pd.Series
    input_features: list[str]
    feature_types: dict
    preprocessor: object            # callable() -> unfitted sklearn transformer (fitted on training data only)
    candidates: list[Candidate]
    target_definition: str
    preprocessing_description: str
    excluded_features: list[dict] = field(default_factory=list)
    derived_features: list[dict] = field(default_factory=list)
    cleaning: dict = field(default_factory=dict)
    groups: np.ndarray | None = None
    order: np.ndarray | None = None
    split_override_note: str = ""
    min_pr_auc: float = 0.5
    limitations: list[str] = field(default_factory=list)
    source_note: str = ""
    is_fixture: bool = False
    max_fpr: float | None = None            # None: choose the threshold by F2; a number: highest recall with at most this false-positive rate


@dataclass
class TrainResult:
    pipeline: CalibratedModel
    metadata: dict
    report_md: str
    test_proba: np.ndarray
    test_y: np.ndarray


def _pipe(spec: TaskSpec, clf) -> Pipeline:
    return Pipeline([("pre", spec.preprocessor()), ("clf", clf)])


def _oof(pipe: Pipeline, X, y, folds: int, seed: int) -> np.ndarray:
    """Out-of-fold probability of fraud for every training row (each row is scored by a model that never saw it)."""
    out = np.zeros(len(y))
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for tr, va in skf.split(X, y):
        m = clone(pipe)
        m.fit(X.iloc[tr], y.iloc[tr])
        out[va] = m.predict_proba(X.iloc[va])[:, list(m.classes_).index(1)]
    return out


def _grid_name(base: str, params: dict) -> str:
    return base if not params else base + " " + json.dumps(params, sort_keys=True, default=str)


def _env() -> dict:
    return {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "numpy": np.__version__,
            "pandas": pd.__version__, "joblib": joblib.__version__}


# ---------------------------------------------------------------------------------------------------------- experiment
def train_task(spec: TaskSpec, split_method: str = "stratified", folds: int = 4, seed: int = SEED, log=print) -> TrainResult:
    """Split -> compare candidates by cross-validation on the training partition -> choose the threshold and calibrator on
    out-of-fold predictions -> refit -> evaluate ONCE on the untouched test partition -> validation gate."""
    X, y = spec.X.reset_index(drop=True), spec.y.reset_index(drop=True).astype(int)
    if list(X.columns) != spec.input_features:
        raise ValueError("X columns must equal input_features exactly.")
    if y.value_counts().min() < 30:
        raise ValueError("Each class needs at least 30 rows to train and evaluate.")

    if split_method == "group":
        if spec.groups is None:
            raise ValueError("A group split needs groups.")
        split = group_split(y, spec.groups, seed=seed)
    elif split_method == "chronological":
        if spec.order is None:
            raise ValueError("A chronological split needs an order column.")
        split = chronological_split(spec.order)
    else:
        split = stratified_split(y, seed=seed)
    if spec.split_override_note:
        split.note = (split.note + " " + spec.split_override_note).strip()
    assert_no_overlap(split, spec.groups if split_method == "group" else None)
    X_tr, y_tr = X.iloc[split.train_idx].reset_index(drop=True), y.iloc[split.train_idx].reset_index(drop=True)
    X_te, y_te = X.iloc[split.test_idx].reset_index(drop=True), y.iloc[split.test_idx].reset_index(drop=True)
    log(f"split: {split.method}; train {len(y_tr):,} (fraud {int(y_tr.sum())}), test {len(y_te):,} (fraud {int(y_te.sum())})")

    # --- baseline + candidates, compared by cross-validated PR-AUC on the TRAINING partition only
    baselines, rows, oof_store = {}, [], {}
    dummy = _pipe(spec, DummyClassifier(strategy="prior"))
    dummy_oof = _oof(dummy, X_tr, y_tr, folds, seed)
    baselines["dummy_prior"] = {"cv_pr_auc": float(average_precision_score(y_tr, dummy_oof)), "note": "always predicts the training fraud rate"}
    for cand in spec.candidates:
        for params in cand.params:
            name = _grid_name(cand.name, params)
            log(f"cross-validating {name} ...")
            pipe = _pipe(spec, cand.make(**params))
            oof = _oof(pipe, X_tr, y_tr, folds, seed)
            ap = float(average_precision_score(y_tr, oof))
            rows.append({"name": name, "family": cand.name, "params": params, "cv_pr_auc": ap, "cv_roc_auc": float(roc_auc_score(y_tr, oof))})
            oof_store[name] = (pipe, oof)
    best = max(rows, key=lambda r: r["cv_pr_auc"])
    best_pipe, best_oof = oof_store[best["name"]]
    for fam in {r["family"] for r in rows}:                      # best score per family = the baseline comparison table
        baselines[fam] = {"cv_pr_auc": max(r["cv_pr_auc"] for r in rows if r["family"] == fam)}
    log(f"selected: {best['name']} (cross-validated PR-AUC {best['cv_pr_auc']:.4f})")

    # --- calibration + threshold: out-of-fold predictions of the chosen model, training partition only
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(best_oof, y_tr)
    oof_cal = iso.predict(best_oof)
    threshold = select_threshold_at_fpr(y_tr, oof_cal, spec.max_fpr) if spec.max_fpr else select_threshold(y_tr, oof_cal)
    validation_metrics = full_metrics(y_tr, oof_cal, threshold["value"])

    # --- final fit on the whole training partition, then ONE evaluation on the untouched test partition
    final_base = clone(best_pipe).fit(X_tr, y_tr)
    model = CalibratedModel(final_base, iso, list(spec.input_features))
    raw_te = model.raw_score(X_te)
    cal_te = model.predict_proba(X_te)[:, 1]
    test = full_metrics(y_te, cal_te, threshold["value"])
    raw_check = {"brier_raw": float(brier_score_loss(y_te, np.clip(raw_te, 0, 1))), "ece_raw": expected_calibration_error(y_te, raw_te),
                 "brier_calibrated": test["brier"], "ece_calibrated": test["calibration_error_ece"]}
    dummy_fit = clone(dummy).fit(X_tr, y_tr)
    dummy_test_ap = float(average_precision_score(y_te, dummy_fit.predict_proba(X_te)[:, 1]))
    test["reliability_calibrated"] = reliability_table(y_te, cal_te)
    log(f"test: precision {test['precision']:.3f} recall {test['recall']:.3f} PR-AUC {test['pr_auc']} (dummy {dummy_test_ap:.4f})")

    # --- gate: only a candidate that passes is allowed to become the live model
    checks, failures = [], []

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        if not ok:
            failures.append(f"{name}: {detail}")
    check("held-out test has both classes", test["support_fraud"] > 0 and test["support_legitimate"] > 0)
    check("enough fraud rows in the test partition (>= 30)", test["support_fraud"] >= 30, f"{test['support_fraud']} fraud rows")
    check("test PR-AUC meets the minimum for this task", (test["pr_auc"] or 0) >= spec.min_pr_auc, f"{test['pr_auc']} vs minimum {spec.min_pr_auc}")
    check("beats the do-nothing baseline by a clear margin", (test["pr_auc"] or 0) >= dummy_test_ap + 0.2, f"{test['pr_auc']} vs dummy {dummy_test_ap:.4f}")
    check("no train/test overlap", True, "asserted before fitting")
    check("all metrics are finite numbers", all(np.isfinite(v) for v in (test["precision"], test["recall"], test["f1"], test["brier"])))
    reload = _fresh_process_reload_check(model, X_te)
    check("artifact reloads in a fresh process and reproduces predictions", reload["ok"], reload["detail"])

    now = datetime.now(timezone.utc)
    version = f"{spec.model_name.replace('_', '-')}-{now.strftime('%Y%m%d-%H%M%S')}"
    metadata = {
        "model_name": spec.model_name, "version": version, "trained_at": now.isoformat(), "task": spec.task,
        "is_fixture": spec.is_fixture, "model_type": best["family"], "selected": {"name": best["name"], "params": best["params"]},
        "dataset": spec.dataset, "target": {"column": str(y.name), "definition": spec.target_definition},
        "input_features": list(spec.input_features), "feature_types": spec.feature_types,
        "derived_features": spec.derived_features, "excluded_features": spec.excluded_features,
        "preprocessing": spec.preprocessing_description, "cleaning": spec.cleaning,
        "split": {"method": split.method, "note": split.note, "test_size": TEST_SIZE, "seed": seed, "train_rows": int(len(y_tr)),
                  "test_rows": int(len(y_te)), "train_class_counts": {"legitimate": int((y_tr == 0).sum()), "fraud": int((y_tr == 1).sum())},
                  "test_class_counts": {"legitimate": int((y_te == 0).sum()), "fraud": int((y_te == 1).sum())},
                  "overlap_checked": True, "cross_validation_folds": folds},
        "config": {"seed": seed, "folds": folds, "candidates": [{"name": c.name, "grid": c.params, "note": c.note} for c in spec.candidates]},
        "candidates": rows, "baselines": baselines | {"dummy_prior_test_pr_auc": dummy_test_ap},
        "threshold_info": threshold, "threshold": threshold["value"],
        "calibration": {"method": "isotonic regression fitted on out-of-fold training predictions", **raw_check},
        "metrics": test, "validation_metrics_out_of_fold": validation_metrics,
        "validation": {"passed": not failures, "checks": checks, "failures": failures},
        "environment": _env(), "limitations": spec.limitations, "source_note": spec.source_note,
        # compatibility with the older /pca-demo endpoints
        "features": list(spec.input_features), "data_source": spec.dataset.get("name"), "n_rows": int(len(y)), "n_fraud": int(y.sum()),
    }
    model.version = version
    report = render_report(metadata)
    return TrainResult(model, metadata, report, cal_te, y_te.to_numpy())


def chronological_robustness(spec: TaskSpec, selected: dict, threshold: float, seed: int = SEED) -> dict:
    """A SECOND, informational evaluation: train the already-selected configuration on the oldest 80% and test on the newest 20%.
    It is not used to choose or tune anything: it shows whether performance survives a move forward in time."""
    X, y = spec.X.reset_index(drop=True), spec.y.reset_index(drop=True).astype(int)
    sp = chronological_split(spec.order)
    cand = next(c for c in spec.candidates if c.name == selected["name"].split(" ")[0] or selected["name"].startswith(c.name))
    pipe = _pipe(spec, cand.make(**selected["params"])).fit(X.iloc[sp.train_idx], y.iloc[sp.train_idx])
    p = pipe.predict_proba(X.iloc[sp.test_idx])[:, list(pipe.classes_).index(1)]
    m = full_metrics(y.iloc[sp.test_idx], p, threshold)
    return {"method": sp.method, "train_rows": int(len(sp.train_idx)), "test_rows": int(len(sp.test_idx)),
            "note": "Informational only. Uses the raw (uncalibrated) score with the threshold chosen on the main training partition; "
                    "the calibrated main-split numbers are the official ones.",
            "pr_auc": m["pr_auc"], "roc_auc": m["roc_auc"], "precision": m["precision"], "recall": m["recall"], "fraud_in_test": m["support_fraud"],
            "warning": m.get("warning")}


def _fresh_process_reload_check(model, X_te: pd.DataFrame, n: int = 200) -> dict:
    """Save the model, load it in a NEW python process and compare predictions: catches pickling and import problems."""
    sample = X_te.head(n)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        joblib.dump(model, d / "m.joblib")
        sample.to_pickle(d / "x.pkl")
        code = ("import joblib,pandas as pd,numpy as np,sys;"
                "m=joblib.load(sys.argv[1]);x=pd.read_pickle(sys.argv[2]);"
                "np.save(sys.argv[3], m.predict_proba(x)[:,1])")
        try:
            r = subprocess.run([sys.executable, "-c", code, str(d / "m.joblib"), str(d / "x.pkl"), str(d / "p.npy")],
                               capture_output=True, text=True, timeout=300, cwd=str(Path(__file__).resolve().parents[2]))
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "the fresh-process load timed out"}
        if r.returncode != 0:
            return {"ok": False, "detail": "fresh process failed: " + r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else "unknown error"}
        other = np.load(d / "p.npy")
    here = model.predict_proba(sample)[:, 1]
    ok = bool(np.allclose(other, here, atol=1e-9))
    return {"ok": ok, "detail": f"{len(sample)} rows compared" if ok else "predictions differ after reload"}


def render_report(meta: dict) -> str:
    m, s = meta["metrics"], meta["split"]
    cm = m["confusion_matrix"]
    lines = [
        f"# {meta['model_name']} {meta['version']}", "",
        f"* Dataset: **{meta['dataset'].get('name')}** (licence: {meta['dataset'].get('licence')}; sha256 `{str(meta['dataset'].get('sha256', ''))[:16]}...`)",
        f"* Target: {meta['target']['definition']}",
        f"* Split: {s['method']}. Train {s['train_rows']:,} rows, test {s['test_rows']:,} rows (fraud in test: {s['test_class_counts']['fraud']}).",
        f"* Model: {meta['selected']['name']}. Threshold {meta['threshold']:.4f} ({meta['threshold_info']['objective']}), chosen on {meta['threshold_info']['selected_on']}.",
        f"* Validation gate: **{'PASSED' if meta['validation']['passed'] else 'FAILED'}**", "",
        "## Held-out test results (computed once, on rows never used for fitting, selection, calibration or the threshold)", "",
        f"| Measure | Value |", "|---|---|",
        f"| Accuracy (misleading when fraud is rare) | {m['accuracy']:.4f} |",
        f"| Precision (fraud) | {m['precision']:.4f} |", f"| Recall (fraud) | {m['recall']:.4f} |", f"| F1 (fraud) | {m['f1']:.4f} |",
        f"| PR-AUC (average precision) | {m['pr_auc']:.4f} |", f"| ROC-AUC | {m['roc_auc']:.4f} |",
        f"| False positives / rate | {m['false_positives']:,} / {m['false_positive_rate']:.5f} |",
        f"| False negatives / rate | {m['false_negatives']:,} / {m['false_negative_rate']:.4f} |",
        f"| Fraud prevalence in test | {m['fraud_prevalence']:.5f} |", f"| Test rows | {m['test_rows']:,} |", "",
        f"Confusion matrix: TN {cm['tn']:,}  FP {cm['fp']:,}  FN {cm['fn']:,}  TP {cm['tp']:,}", "",
        f"Do-nothing baseline PR-AUC on the same test rows: {meta['baselines']['dummy_prior_test_pr_auc']:.4f}", "",
        "## Calibration", "", f"Brier score {meta['calibration']['brier_raw']:.5f} (raw) -> {meta['calibration']['brier_calibrated']:.5f} (calibrated); "
        f"calibration error {meta['calibration']['ece_raw']:.5f} -> {meta['calibration']['ece_calibrated']:.5f}.", "",
        "## Candidates compared (cross-validated PR-AUC on the training partition)", "", "| Candidate | CV PR-AUC |", "|---|---|"]
    lines += [f"| {r['name']} | {r['cv_pr_auc']:.4f} |" for r in sorted(meta["candidates"], key=lambda r: -r["cv_pr_auc"])]
    if meta.get("robustness"):
        r = meta["robustness"]["chronological"]
        lines += ["", "## Robustness: train on the oldest 80%, test on the newest 20% (informational)", "",
                  f"PR-AUC {r['pr_auc']}, recall {r['recall']:.3f}, precision {r['precision']:.3f}, fraud rows in that test {r['fraud_in_test']}."]
    lines += ["", "## Validation checks"] + [f"* {'PASS' if c['passed'] else 'FAIL'}: {c['check']} {c['detail']}" for c in meta["validation"]["checks"]]
    if meta["limitations"]:
        lines += ["", "## Limitations"] + [f"* {x}" for x in meta["limitations"]]
    return "\n".join(lines) + "\n"
