"""Approach A: a separate demonstration model for the Kaggle credit-card dataset.

The Kaggle columns V1-V28 are anonymised PCA components. They CANNOT be computed from ordinary
payment-form fields, so this model is NOT connected to the payment form. It is exposed through its own
clearly labelled endpoints and accepts only rows that already contain the 30 dataset features.
Source: https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud (ULB Machine Learning Group, database
contents licence DbCL v1.0; real but anonymised European card transactions from September 2013).
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from .evaluation import evaluate

FEATURES = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount"]
TARGET = "Class"
SEED = 42
THRESHOLD = 0.5
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models" / "pca_demo_model.joblib"
SOURCE_NOTE = ("Kaggle 'Credit Card Fraud Detection' (ULB). Real, anonymised card transactions; V1-V28 are PCA "
               "components, so rows cannot be created from payment-form fields.")


class DatasetError(ValueError):
    """The dataset is missing, unreadable, or does not match the expected schema."""


def validate(df: pd.DataFrame) -> dict:
    """Raise DatasetError for fatal problems; return a dict describing non-fatal cleaning that will be applied."""
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise DatasetError(f"Missing required columns: {', '.join(missing)}. Expected Time, V1..V28, Amount and "
                           f"the label column '{TARGET}' (0 = legitimate, 1 = fraud).")
    sub = df[FEATURES + [TARGET]]
    numeric = sub.apply(pd.to_numeric, errors="coerce")
    non_numeric = int(numeric.isna().sum().sum() - sub.isna().sum().sum())
    if non_numeric:
        raise DatasetError(f"{non_numeric} non-numeric values found in feature/label columns.")
    labels = set(numeric[TARGET].dropna().unique().tolist())
    if not labels <= {0, 1}:
        raise DatasetError(f"'{TARGET}' must contain only 0 and 1; found {sorted(labels)}.")
    return {
        "rows": int(len(df)),
        "missing_values": int(numeric.isna().sum().sum()),
        "infinite_values": int(np.isinf(numeric.to_numpy(dtype=float)).sum()),
        "duplicate_rows": int(df.duplicated(subset=FEATURES + [TARGET]).sum()),
    }


def clean(df: pd.DataFrame):
    """Drop rows with missing/infinite values and exact duplicates (so duplicates cannot leak across the split).
    Returns (cleaned_df, report) so the impact is visible, never silent."""
    info = validate(df)
    work = df[FEATURES + [TARGET]].apply(pd.to_numeric).replace([np.inf, -np.inf], np.nan)
    bad = int(work.isna().any(axis=1).sum())
    work = work.dropna()
    dups = int(work.duplicated().sum())
    work = work.drop_duplicates()
    work[TARGET] = work[TARGET].astype(int)
    return work.reset_index(drop=True), {**info, "dropped_missing_or_infinite_rows": bad, "dropped_duplicate_rows": dups,
                                         "rows_after_cleaning": int(len(work))}


def train(df: pd.DataFrame, source: str, n_estimators: int = 150, threshold: float | None = None):
    threshold = THRESHOLD if threshold is None else float(threshold)
    if not 0.0 <= threshold <= 1.0:
        raise DatasetError("threshold must be between 0 and 1")
    work, cleaning = clean(df)
    y = work[TARGET]
    if y.value_counts().min() < 10:
        raise DatasetError("Each class needs at least 10 rows after cleaning.")
    X = work[FEATURES]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=SEED, stratify=y)
    pipe = Pipeline([("rf", RandomForestClassifier(n_estimators=n_estimators, min_samples_leaf=2,
                                                   class_weight="balanced_subsample", random_state=SEED, n_jobs=-1))])
    pipe.fit(X_tr, y_tr)                    # test split is never used for fitting
    proba = pipe.predict_proba(X_te)[:, list(pipe.classes_).index(1)]
    metrics = evaluate(y_te, proba, threshold)
    now = datetime.now(timezone.utc)
    meta = {
        "version": now.strftime("pca-%Y%m%d-%H%M%S"), "trained_at": now.isoformat(), "model_type": "RandomForestClassifier",
        "data_source": source, "source_note": SOURCE_NOTE, "features": FEATURES, "target": TARGET,
        "split": {"test_size": 0.2, "stratified": True, "random_state": SEED},
        "params": pipe.named_steps["rf"].get_params(), "threshold": threshold, "cleaning": cleaning,
        "n_rows": int(len(work)), "n_fraud": int(y.sum()), "metrics": metrics,
    }
    meta["params"] = {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v)) for k, v in meta["params"].items()}
    return pipe, meta


def save(pipe, meta: dict, path: Path = DEFAULT_PATH) -> Path:
    """Write only after the artifact reloads and predicts; never leaves a half-written model behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as t:
        tmp = Path(t.name)
    try:
        joblib.dump({"pipeline": pipe, "metadata": meta}, tmp)
        back = joblib.load(tmp)
        p = float(back["pipeline"].predict_proba(pd.DataFrame([[0.0] * len(FEATURES)], columns=FEATURES))[0][1])
        if not 0.0 <= p <= 1.0:
            raise RuntimeError("Reloaded model returned an invalid probability")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


class PcaPredictor:
    def __init__(self, high: float = 0.7, medium: float = 0.3, threshold: float | None = None):
        self.high, self.medium, self.threshold_override = high, medium, threshold
        self.pipeline, self.metadata, self.error = None, None, "PCA demo model not loaded"

    @property
    def available(self):
        return self.pipeline is not None

    def load(self, path: Path = DEFAULT_PATH):
        self.pipeline, self.metadata = None, None
        path = Path(path)
        if not path.exists():
            self.error = "PCA demo model not trained. Place creditcard.csv in backend/data and run: python train_model.py --schema pca"
            return
        try:
            b = joblib.load(path)       # trusted local file only
            if b["metadata"].get("features") != FEATURES:
                self.error = "PCA demo model has a different feature list. Retrain it."
                return
            self.pipeline, self.metadata, self.error = b["pipeline"], b["metadata"], ""
        except Exception as exc:
            self.error = f"Could not read PCA demo model ({type(exc).__name__})"

    def predict(self, features: dict) -> dict:
        row = pd.DataFrame([{k: features[k] for k in FEATURES}])[FEATURES]
        p = float(self.pipeline.predict_proba(row)[0][list(self.pipeline.classes_).index(1)])
        thr = float(self.threshold_override if self.threshold_override is not None else self.metadata["threshold"])
        return {"prediction": int(p >= thr), "fraud_probability": round(p, 6),
                "risk_level": "High" if p >= self.high else "Medium" if p >= self.medium else "Low",
                "threshold": thr, "model_version": self.metadata["version"]}
