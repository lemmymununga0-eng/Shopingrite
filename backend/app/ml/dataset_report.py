"""Reads a real CSV and reports on it. Nothing is assumed about row counts or contents."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import feature_schema as pay
from . import pca_demo

MAX_BYTES = 2_000_000_000


class DatasetFileError(ValueError):
    """File missing, wrong type, empty, too large or unreadable."""


def load_csv(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise DatasetFileError(f"File not found: {path}")
    if path.suffix.lower() != ".csv":
        raise DatasetFileError(f"Expected a .csv file, got '{path.suffix}'")
    size = path.stat().st_size
    if size == 0:
        raise DatasetFileError("File is empty")
    if size > MAX_BYTES:
        raise DatasetFileError("File is larger than 2 GB; refusing to load it")
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise DatasetFileError(f"File could not be read as CSV ({type(exc).__name__}: {exc})")
    if df.empty:
        raise DatasetFileError("File has a header but no rows")
    return df


def detect_schema(df: pd.DataFrame) -> str:
    cols = set(df.columns)
    if set(pca_demo.FEATURES) <= cols:
        return "pca"
    if set(pay.FEATURES) <= cols:
        return "payment"
    return "unknown"


def inspect(path: Path, schema: str = "auto", target: str | None = None) -> dict:
    """Return a machine-readable report. `target` overrides the label column name."""
    path = Path(path)
    df = load_csv(path)
    if schema == "auto":
        schema = detect_schema(df)
    expected = {"pca": (pca_demo.FEATURES, pca_demo.TARGET), "payment": (pay.FEATURES, pay.TARGET)}.get(schema)
    label = target or (expected[1] if expected else None)
    num = df.select_dtypes(include=[np.number])
    report = {
        "path": str(path), "size_bytes": int(path.stat().st_size), "rows": int(len(df)), "columns": int(df.shape[1]),
        "column_types": {c: str(t) for c, t in df.dtypes.items()},
        "missing_per_column": {c: int(n) for c, n in df.isna().sum().items() if n},
        "duplicate_rows": int(df.duplicated().sum()),
        "infinite_values": int(np.isinf(num.to_numpy(dtype=float)).sum()) if not num.empty else 0,
        "detected_schema": schema, "target_column": label, "problems": [],
        "describe": json.loads(num.describe().round(4).to_json()) if not num.empty else {},
    }
    if expected is None:
        report["problems"].append("Columns do not match the PCA (Time, V1..V28, Amount) or payment-form schema. "
                                  "Pick a schema or fix the columns; training will not guess.")
    else:
        missing = [c for c in expected[0] if c not in df.columns]
        if missing:
            report["problems"].append(f"Missing feature columns: {missing}")
    if label is None or label not in df.columns:
        report["problems"].append(f"Target column '{label}' not found. Pass --target NAME if your label has another name.")
    else:
        counts = df[label].value_counts(dropna=False).to_dict()
        report["label_counts"] = {str(k): int(v) for k, v in counts.items()}
        if not set(df[label].dropna().unique().tolist()) <= {0, 1}:
            report["problems"].append(f"Target '{label}' must contain only 0 and 1, found {sorted(map(str, counts))}.")
        else:
            legit, fraud = int(counts.get(0, 0)), int(counts.get(1, 0))
            report["legitimate"], report["fraud"] = legit, fraud
            report["fraud_percent"] = round(100 * fraud / len(df), 4)
            report["imbalance_ratio"] = round(legit / fraud, 1) if fraud else None
            if fraud == 0 or legit == 0:
                report["problems"].append("Only one class present: a classifier cannot be trained.")
            elif fraud < 30:
                report["problems"].append(f"Only {fraud} fraud rows: evaluation will be unreliable.")
    report["training_ready"] = not report["problems"]
    return report


def render_text(r: dict) -> str:
    out = [f"Dataset: {r['path']}", f"Size: {r['size_bytes']:,} bytes   Rows: {r['rows']:,}   Columns: {r['columns']}",
           f"Detected schema: {r['detected_schema']}   Target: {r['target_column']}",
           f"Duplicate rows: {r['duplicate_rows']:,}   Infinite values: {r['infinite_values']}"]
    out.append("Missing values: " + (", ".join(f"{c}={n}" for c, n in r["missing_per_column"].items()) or "none"))
    if "legitimate" in r:
        out.append(f"Legitimate: {r['legitimate']:,}   Fraud: {r['fraud']:,}   Fraud %: {r['fraud_percent']}   "
                   f"Imbalance (legit per fraud): {r['imbalance_ratio']}")
    out.append("Column types: " + ", ".join(f"{c}:{t}" for c, t in list(r["column_types"].items())[:40]))
    out.append("Problems: " + ("; ".join(r["problems"]) if r["problems"] else "none"))
    out.append("TRAINING READY" if r["training_ready"] else "NOT READY FOR TRAINING")
    return "\n".join(out)


def write_reports(r: dict, out_dir: Path, name: str = "dataset_report"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    (out_dir / f"{name}.txt").write_text(render_text(r) + "\n", encoding="utf-8")
