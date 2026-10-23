"""Shared helpers for the paper's experiments. Everything here is deterministic (fixed seeds) and reads the same cleaned data
and the same training framework the application uses (backend/app/ml)."""
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
RESULTS = ROOT / "research" / "results"
FIGS = ROOT / "research" / "figures"
SCRATCH = RESULTS / "_scratch"
for d in (RESULTS, FIGS, SCRATCH):
    d.mkdir(parents=True, exist_ok=True)
SEED = 42


def save(name: str, obj) -> Path:
    p = RESULTS / f"{name}.json"
    p.write_text(json.dumps(obj, indent=2, default=_default), encoding="utf8")
    print(f"wrote {p.relative_to(ROOT)}")
    return p


def load(name: str):
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf8"))


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def environment() -> dict:
    import pandas as pd
    import scipy
    import sklearn
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        commit = ""
    return {"python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(), "numpy": np.__version__,
            "pandas": pd.__version__, "scikit-learn": sklearn.__version__, "scipy": scipy.__version__, "git_commit": commit, "seed": SEED}


class Timer:
    def __init__(self):
        self.t = time.time()

    def lap(self) -> float:
        now = time.time()
        d, self.t = now - self.t, now
        return round(d, 1)


# ------------------------------------------------------------------------------------------------------------- statistics
def confusion_extras(cm: dict) -> dict:
    tn, fp, fn, tp = cm["tn"], cm["fp"], cm["fn"], cm["tp"]
    denom = ((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5
    return {"specificity": tn / (tn + fp) if tn + fp else None, "mcc": (tp * tn - fp * fn) / denom if denom else 0.0}


def stratified_bootstrap(y, P: dict, thr: dict, B: int = 1000, seed: int = 7, pr_auc=True) -> dict:
    """Percentile bootstrap that resamples fraud and legitimate rows separately (so every resample keeps the original class
    counts). The SAME resample is used for every model, which makes differences between models paired."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    rng = np.random.default_rng(seed)
    y = np.asarray(y).astype(int)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    names = list(P)
    keys = ("pr_auc", "roc_auc", "precision", "recall", "f1", "mcc")
    draws = {n: {k: np.empty(B) for k in keys} for n in names}
    for b in range(B):
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        yy = y[idx]
        for n in names:
            p = np.asarray(P[n])[idx]
            pred = p >= thr[n]
            tp = int(((pred == 1) & (yy == 1)).sum()); fp = int(((pred == 1) & (yy == 0)).sum())
            fn = int(((pred == 0) & (yy == 1)).sum()); tn = int(((pred == 0) & (yy == 0)).sum())
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            d = draws[n]
            d["precision"][b], d["recall"][b] = prec, rec
            d["f1"][b] = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            den = ((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5
            d["mcc"][b] = (tp * tn - fp * fn) / den if den else 0.0
            d["pr_auc"][b] = average_precision_score(yy, p) if pr_auc else np.nan
            d["roc_auc"][b] = roc_auc_score(yy, p)
    ci = {n: {k: {"lo": float(np.percentile(v, 2.5)), "hi": float(np.percentile(v, 97.5)), "sd": float(v.std())} for k, v in d.items()}
          for n, d in draws.items()}
    paired = {}
    for i, a in enumerate(names):
        for c in names[i + 1:]:
            for k in ("pr_auc", "roc_auc", "f1"):
                diff = draws[a][k] - draws[c][k]
                paired[f"{a} - {c} [{k}]"] = {"mean": float(diff.mean()), "lo": float(np.percentile(diff, 2.5)), "hi": float(np.percentile(diff, 97.5)),
                                              "p_two_sided": float(min(1.0, 2 * min((diff <= 0).mean(), (diff >= 0).mean())))}
    return {"B": B, "seed": seed, "ci95": ci, "paired_differences": paired}


def mcnemar_exact(y, pred_a, pred_b) -> dict:
    """Exact McNemar test on the rows where the two classifiers disagree about being right (Dietterich, 1998)."""
    from scipy.stats import binomtest
    y, a, b = np.asarray(y), np.asarray(pred_a), np.asarray(pred_b)
    a_ok, b_ok = a == y, b == y
    only_a, only_b = int((a_ok & ~b_ok).sum()), int((~a_ok & b_ok).sum())
    n = only_a + only_b
    return {"a_right_b_wrong": only_a, "b_right_a_wrong": only_b, "p_value": float(binomtest(only_a, n, 0.5).pvalue) if n else 1.0}
