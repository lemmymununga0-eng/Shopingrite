"""Single source of truth for the model's input features.

The payment form, the API schema, the training script and the predictor all use
this module, so they cannot drift apart. Nothing here is mapped from unrelated
fields: every feature is something the payment form really collects.
"""
import hashlib
import json

TARGET = "is_fraud"

PAYMENT_METHODS = ["Card", "Bank Transfer", "Mobile Money"]
BRANCHES = ["Online", "Johannesburg CBD", "Cape Town V&A", "Durban North", "Pretoria Central"]

NUMERIC_FEATURES = ["amount", "hour", "failed_attempts", "new_device", "international", "customer_avg_spend"]
CATEGORICAL_FEATURES = ["payment_method", "branch"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# (min, max) accepted by the API and by dataset validation.
RANGES = {
    "amount": (0.01, 1_000_000.0),
    "hour": (0, 23),
    "failed_attempts": (0, 10),
    "new_device": (0, 1),
    "international": (0, 1),
    "customer_avg_spend": (0.0, 1_000_000.0),
}
CATEGORIES = {"payment_method": PAYMENT_METHODS, "branch": BRANCHES}


def schema_hash() -> str:
    """Short fingerprint of the feature schema, stored inside the model artifact."""
    payload = json.dumps(
        {"features": FEATURES, "ranges": RANGES, "categories": CATEGORIES, "target": TARGET},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def validate_dataframe(df):
    """Return a list of human-readable problems with a training dataframe (empty list = valid)."""
    problems = []
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        return [f"Missing required columns: {', '.join(missing)}"]
    nulls = df[FEATURES + [TARGET]].isna().sum()
    for col, n in nulls.items():
        if n:
            problems.append(f"Column '{col}' has {int(n)} missing values")
    if problems:
        return problems
    labels = set(df[TARGET].unique().tolist())
    if not labels <= {0, 1}:
        problems.append(f"Target '{TARGET}' must contain only 0 and 1, found {sorted(labels)}")
    elif len(labels) < 2:
        problems.append("Target must contain both classes (0 and 1)")
    for col, (lo, hi) in RANGES.items():
        bad = int(((df[col] < lo) | (df[col] > hi)).sum())
        if bad:
            problems.append(f"Column '{col}' has {bad} values outside [{lo}, {hi}]")
    for col, allowed in CATEGORIES.items():
        bad = sorted(set(df[col].unique()) - set(allowed))
        if bad:
            problems.append(f"Column '{col}' has unknown categories: {bad}")
    return problems
