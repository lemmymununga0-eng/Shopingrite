"""Synthetic development dataset.

IMPORTANT: this data is generated, not real. The `is_fraud` label is produced from a
hand-written risk formula (larger-than-usual amounts, night hours, failed attempts, new
device, international) plus random noise. A model trained on it learns that formula, so its
evaluation metrics say nothing about real-world fraud detection.
"""
import numpy as np
import pandas as pd

from .feature_schema import BRANCHES, PAYMENT_METHODS, TARGET


def _hour_probs():
    w = np.array([1, 1, 1, 1, 1, 2, 3, 5, 6, 6, 6, 7, 8, 8, 7, 7, 7, 8, 8, 7, 5, 4, 2, 1], dtype=float)
    return w / w.sum()


def generate(n_rows: int = 20000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    avg = np.round(rng.lognormal(mean=5.3, sigma=0.6, size=n_rows), 2).clip(10, 20000)
    ratio = rng.lognormal(mean=0.0, sigma=0.7, size=n_rows)
    amount = np.round(avg * ratio, 2).clip(0.5, 500000)
    hour = rng.choice(24, size=n_rows, p=_hour_probs())
    failed = rng.choice([0, 1, 2, 3, 4, 5], size=n_rows, p=[0.82, 0.10, 0.04, 0.02, 0.01, 0.01])
    new_device = (rng.random(n_rows) < 0.12).astype(int)
    international = (rng.random(n_rows) < 0.06).astype(int)
    method = rng.choice(PAYMENT_METHODS, size=n_rows, p=[0.6, 0.15, 0.25])
    branch = rng.choice(BRANCHES, size=n_rows, p=[0.25, 0.25, 0.2, 0.15, 0.15])

    night = (hour <= 4).astype(int)
    logit = (
        -6.0
        + 2.0 * np.log1p(amount / (avg + 1.0))
        + 1.5 * night
        + 0.9 * failed
        + 2.0 * new_device
        + 2.3 * international
        + 0.6 * ((method == "Mobile Money") & (new_device == 1))
        + rng.normal(0, 0.5, n_rows)
    )
    p = 1.0 / (1.0 + np.exp(-logit))
    label = (rng.random(n_rows) < p).astype(int)
    return pd.DataFrame({
        "amount": amount, "hour": hour, "failed_attempts": failed, "new_device": new_device,
        "international": international, "customer_avg_spend": avg,
        "payment_method": method, "branch": branch, TARGET: label,
    })
