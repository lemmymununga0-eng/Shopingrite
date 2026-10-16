"""Loads the model artifact and runs genuine inference."""
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd

from . import feature_schema as fs


class ModelUnavailable(Exception):
    """No usable model is loaded (missing, corrupt, or incompatible schema)."""


@dataclass
class Prediction:
    probability: float
    is_fraud: bool
    risk: str
    model_version: str
    contributing_factors: list


class Predictor:
    def __init__(self, high: float = 0.7, medium: float = 0.3):
        self.high, self.medium = high, medium
        self.pipeline = None
        self.metadata = None
        self.error = "No model loaded"

    @property
    def available(self) -> bool:
        return self.pipeline is not None

    def load(self, path: Path):
        self.pipeline, self.metadata = None, None
        path = Path(path)
        if not path.exists():
            self.error = f"Model file not found ({path.name}). Run: python -m app.ml.train_model --synthetic"
            return
        try:
            bundle = joblib.load(path)       # only load artifacts you trained yourself
            meta = bundle["metadata"]
            pipe = bundle["pipeline"]
        except Exception as exc:
            self.error = f"Could not read model file ({type(exc).__name__})"
            return
        if meta.get("schema_hash") != fs.schema_hash():
            self.error = "Model was trained with a different feature schema. Retrain the model."
            return
        self.pipeline, self.metadata, self.error = pipe, meta, ""

    def risk_level(self, p: float) -> str:
        return "High" if p >= self.high else "Medium" if p >= self.medium else "Low"

    def predict(self, features: dict) -> Prediction:
        if not self.available:
            raise ModelUnavailable(self.error)
        row = pd.DataFrame([{k: features[k] for k in fs.FEATURES}])[fs.FEATURES]
        p = float(self.pipeline.predict_proba(row)[0][list(self.pipeline.classes_).index(1)])
        return Prediction(
            probability=p,
            is_fraud=p >= float(self.metadata.get("threshold", 0.5)),
            risk=self.risk_level(p),
            model_version=self.metadata["version"],
            contributing_factors=self.rule_based_factors(features),
        )

    @staticmethod
    def rule_based_factors(f: dict) -> list:
        """Plain-language observations about THIS transaction's inputs.

        These are simple fixed-rule comparisons, NOT an explanation of the model's decision.
        """
        out = []
        avg = f["customer_avg_spend"]
        if avg > 0 and f["amount"] > 3 * avg:
            out.append("Amount is more than 3x the customer's average spend")
        if f["hour"] <= 4:
            out.append("Transaction made between 00:00 and 04:59")
        if f["failed_attempts"] >= 2:
            out.append(f"{f['failed_attempts']} failed attempts before this transaction")
        if f["new_device"]:
            out.append("Transaction came from a new device")
        if f["international"]:
            out.append("International transaction")
        return out

    def global_importance(self) -> list:
        """Overall feature importance learned from the training data (NOT per-transaction)."""
        if not self.available:
            return []
        names = self.pipeline.named_steps["pre"].get_feature_names_out()
        imps = self.pipeline.named_steps["rf"].feature_importances_
        ranked = sorted(zip(names, imps), key=lambda t: -t[1])[:8]
        return [{"feature": n.split("__", 1)[-1], "importance": round(float(i), 4)} for n, i in ranked]
