"""Train the Random Forest fraud model.

Usage (from the backend folder):
    python -m app.ml.train_model --synthetic            # generate + train on synthetic data
    python -m app.ml.train_model --csv data/transactions.csv

The artifact is written only after training, evaluation and a reload-and-predict check succeed.
"""
import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from . import feature_schema as fs
from .evaluation import evaluate, save_confusion_matrix_png
from .model_metadata import ModelMetadata
from .synthetic import generate

SEED = 42
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "fraud_model.joblib"


def build_pipeline(n_estimators: int = 200) -> Pipeline:
    pre = ColumnTransformer([
        ("num", "passthrough", fs.NUMERIC_FEATURES),
        ("cat", OneHotEncoder(categories=[fs.CATEGORIES[c] for c in fs.CATEGORICAL_FEATURES],
                              handle_unknown="error"), fs.CATEGORICAL_FEATURES),
    ])
    rf = RandomForestClassifier(n_estimators=n_estimators, min_samples_leaf=3,
                                class_weight="balanced_subsample", random_state=SEED, n_jobs=-1)
    return Pipeline([("pre", pre), ("rf", rf)])


def train(df: pd.DataFrame, data_source: str, is_synthetic: bool, threshold: float = 0.3,
          n_estimators: int = 200):
    """Train on `df`; return (pipeline, metadata). Raises ValueError for invalid data."""
    problems = fs.validate_dataframe(df)
    if problems:
        raise ValueError("Dataset validation failed:\n- " + "\n- ".join(problems))
    dups = int(df.duplicated(subset=fs.FEATURES + [fs.TARGET]).sum())
    if dups:                                    # exact duplicates could appear in both splits and inflate scores
        df = df.drop_duplicates(subset=fs.FEATURES + [fs.TARGET]).reset_index(drop=True)
    X = df[fs.FEATURES]
    y = df[fs.TARGET].astype(int)
    if y.value_counts().min() < 10:
        raise ValueError("Each class needs at least 10 rows to train and evaluate.")
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=SEED, stratify=y)
    pipe = build_pipeline(n_estimators)
    pipe.fit(X_tr, y_tr)                      # only the training split is used for fitting
    proba = pipe.predict_proba(X_te)[:, list(pipe.classes_).index(1)]
    metrics = evaluate(y_te, proba, threshold)
    metrics["train_rows"] = int(len(y_tr))
    metrics["test_fraud_rows"] = metrics["support_fraud"]      # name used by the Settings page
    now = datetime.now(timezone.utc)
    meta = ModelMetadata(
        version=now.strftime("rf-%Y%m%d-%H%M%S"), trained_at=now.isoformat(),
        schema_hash=fs.schema_hash(), data_source=data_source, is_synthetic=is_synthetic,
        n_rows=int(len(df)), n_fraud=int(y.sum()), threshold=threshold, metrics=metrics,
        random_seed=SEED,
    )
    meta.metrics["dropped_duplicate_rows"] = dups
    return pipe, meta


def save_artifact(pipe, meta: ModelMetadata, path: Path):
    """Write the artifact only if it reloads and produces a valid probability."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {"pipeline": pipe, "metadata": meta.to_dict()}
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        joblib.dump(bundle, tmp_path)
        loaded = joblib.load(tmp_path)
        sample = pd.DataFrame([{"amount": 100.0, "hour": 12, "failed_attempts": 0, "new_device": 0,
                                "international": 0, "customer_avg_spend": 100.0,
                                "payment_method": "Card", "branch": "Online"}])[fs.FEATURES]
        p = float(loaded["pipeline"].predict_proba(sample)[0][1])
        if np.isnan(p) or not (0.0 <= p <= 1.0):
            raise RuntimeError("Reloaded model returned an invalid probability")
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return path


REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _fmt(x):
    return "n/a" if x is None else f"{x:.3f}"


def write_report(name: str, meta: dict):
    """Save a JSON report, a short text report and a confusion-matrix image under backend/reports."""
    import json
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    m = meta["metrics"]
    (REPORTS_DIR / f"{name}_training_report.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    cm = m["confusion_matrix"]
    lines = [
        f"Model {meta['version']}  ({meta['model_type']})", f"Data source: {meta['data_source']}",
        f"Rows used: {meta['n_rows']}  fraud: {meta['n_fraud']}  test rows: {m['test_rows']} "
        f"(legit {m['support_legitimate']}, fraud {m['support_fraud']})",
        f"Threshold: {m['threshold']}", f"Accuracy {_fmt(m['accuracy'])} (misleading when fraud is rare)",
        f"Precision {_fmt(m['precision'])}  Recall {_fmt(m['recall'])}  F1 {_fmt(m['f1'])}",
        f"PR-AUC {_fmt(m['pr_auc'])}  ROC-AUC {_fmt(m['roc_auc'])}",
        f"Confusion matrix: TN {cm['tn']}  FP {cm['fp']}  FN {cm['fn']}  TP {cm['tp']}",
        "FN = fraud missed (customer loses money). FP = good payment flagged (customer annoyed, analyst time).",
    ]
    if m.get("warning"):
        lines.append("WARNING: " + m["warning"])
    (REPORTS_DIR / f"{name}_training_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    png = save_confusion_matrix_png(cm, REPORTS_DIR / f"{name}_confusion_matrix.png", f"{name} ({meta['version']})")
    return lines, png


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", choices=["payment", "pca"], default="payment",
                    help="payment = model behind the payment form (default); pca = separate Kaggle V1-V28 demo model")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--synthetic", action="store_true", help="payment schema only: generate the synthetic development dataset")
    src.add_argument("--csv", type=Path, help="path to a CSV (pca default: data/creditcard.csv)")
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.schema == "pca":
        from . import pca_demo
        if args.synthetic:
            print("ERROR: the PCA demo model only trains on the real Kaggle dataset (no synthetic fallback).")
            return 1
        csv = args.csv or (DATA_DIR / "creditcard.csv")
        if not csv.exists():
            print(f"ERROR: dataset not found: {csv}\nDownload creditcard.csv from "
                  "https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud and place it there "
                  "(see backend/data/README.md), or run: python scripts/download_kaggle.py")
            return 1
        try:
            pipe, meta = pca_demo.train(pd.read_csv(csv), str(csv))
        except (ValueError, pd.errors.ParserError) as exc:
            print(f"ERROR: {exc}")
            return 1
        out = pca_demo.save(pipe, meta, args.out or pca_demo.DEFAULT_PATH)
        lines, png = write_report("pca_demo", meta)
        print("\n".join(lines))
        print(f"Cleaning: {meta['cleaning']}")
        print(f"Saved model to {out}" + (f"; confusion matrix image: {png}" if png else ""))
        return 0

    if args.synthetic:
        print(f"Generating {args.rows} SYNTHETIC rows (labels come from a hand-written formula, not real fraud).")
        df, source, synth = generate(args.rows, SEED), "synthetic", True
    elif args.csv:
        if not args.csv.exists():
            print(f"ERROR: dataset not found: {args.csv}")
            return 1
        df, source, synth = pd.read_csv(args.csv), str(args.csv), False
    else:
        print("ERROR: choose --synthetic or --csv PATH for the payment schema.")
        return 1
    try:
        pipe, meta = train(df, source, synth)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    save_artifact(pipe, meta, args.out or DEFAULT_MODEL_PATH)
    lines, png = write_report("payment_model", meta.to_dict())
    print("\n".join(lines))
    print(f"Saved model {meta.version} to {args.out or DEFAULT_MODEL_PATH}" + (f"; image: {png}" if png else ""))
    if synth:
        print("NOTE: metrics are from synthetic data and do not show real-world fraud-detection performance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
