"""Serving layer for the verified-data models (credit-card fraud, PaySim mobile money, URL phishing).

Loaded once at application start (see factory.py), never inside a request. The service never invents an answer:

  status "ok"                      a genuine prediction from a validated, checksum-verified model
  status "unsupported_input_schema" the supplied fields do not match what the model was trained on (missing and/or unexpected
                                    names are listed). Nothing is scored and no score is made up.
  status "invalid_input"           the field names match but a value is not acceptable (not a number, out of range, unknown category)
  status "model_unavailable"       the model is not trained / its file is missing, changed, incompatible or failed validation
  status "prediction_failed"       the model raised while scoring; the error type is logged, the details are not returned

A high probability is the model's ESTIMATE that a transaction resembles the fraud in its training data. It is not proof of fraud
and nothing here blocks a customer.
"""
import logging
import math

import pandas as pd

from . import registry, store_schema
from .datasets import PS_TYPES

log = logging.getLogger("fraudguard")

MODEL_NAMES = ("store_grocery", "creditcard_pca", "paysim_mobile_money", "url_phishing")
LABELS = {
    "store_grocery": "Grocery-store order risk (trained on verified store outcomes)",
    "creditcard_pca": "Card transaction fraud (anonymised PCA features, real data)",
    "paysim_mobile_money": "Mobile-money fraud (simulated data)",
    "url_phishing": "ScamWatch phishing URL model (URL text only)",
}
NUMERIC_RANGES = {"amount": (0.0, 1e12), "oldbalanceOrg": (0.0, 1e13), "oldbalanceDest": (0.0, 1e13), "hour_of_day": (0, 23),
                  "dest_is_merchant": (0, 1), "Amount": (0.0, 1e9), "Time": (0.0, 1e9)}
MAX_URL_LENGTH = 2048


class ModelService:
    def __init__(self, root=None, names=MODEL_NAMES):
        self.root, self.names = root or registry.ARTIFACT_ROOT, tuple(names)
        self.loaded: dict[str, registry.LoadResult] = {}

    def load_all(self) -> None:
        for name in self.names:
            self.loaded[name] = registry.load_current(name, self._expected(name), root=self.root)
            r = self.loaded[name]
            log.info("ml model %s: %s %s", name, r.state, r.metadata.get("version", "") or r.detail)

    @staticmethod
    def _expected(name: str):
        return list(store_schema.FEATURE_NAMES) if name == "store_grocery" else None

    def reload(self, name: str) -> registry.LoadResult:
        self.loaded[name] = registry.load_current(name, self._expected(name), root=self.root)
        return self.loaded[name]

    # ------------------------------------------------------------------------------------------------ status
    def result(self, name: str) -> registry.LoadResult:
        return self.loaded.get(name) or registry.LoadResult(registry.NOT_TRAINED, "Not loaded.")

    def status(self, name: str) -> dict:
        r = self.result(name)
        out = {"model": name, "label": LABELS.get(name, name), "state": r.state, "ready": r.ready, "detail": r.detail}
        m = r.metadata
        if m:
            out.update({
                "version": m.get("version"), "trained_at": m.get("trained_at"), "is_fixture": bool(m.get("is_fixture")),
                "experimental": bool(m.get("experimental")), "schema_version": m.get("schema_version"),
                "dataset": {k: m.get("dataset", {}).get(k) for k in ("name", "source", "licence", "licence_status", "sha256", "downloaded_at")},
                "target": m.get("target"), "input_features": m.get("input_features"), "excluded_features": m.get("excluded_features"),
                "split": m.get("split"), "threshold": m.get("threshold"), "threshold_info": m.get("threshold_info"),
                "selected": m.get("selected"), "calibration": m.get("calibration"), "validation": m.get("validation"),
                "test_metrics": _public_metrics(m.get("metrics")), "robustness": m.get("robustness"),
                "baseline_test_pr_auc": (m.get("baselines") or {}).get("dummy_prior_test_pr_auc"),
                "limitations": m.get("limitations"), "environment": m.get("environment"),
                "metrics_note": "Test metrics come from rows held out before training began. They are not live performance."})
        return out

    def all_status(self) -> list[dict]:
        return [self.status(n) for n in self.names]

    # ------------------------------------------------------------------------------------------------ prediction
    def validate_features(self, name: str, features: dict) -> dict | None:
        """None when acceptable, otherwise a response dict (status unsupported_input_schema or invalid_input)."""
        if name == "store_grocery":
            bad = store_schema.validate(features)
            if bad is None and self.result(name).metadata.get("schema_version") != store_schema.SCHEMA_VERSION:
                return {"status": "unsupported_input_schema", "message": "The model was trained on a different schema version.",
                        "missing_features": [], "unexpected_features": [], "required_features": store_schema.FEATURE_NAMES}
            return bad
        required = list(self.result(name).metadata.get("input_features") or [])
        supplied = set(features)
        missing, extra = [f for f in required if f not in supplied], sorted(supplied - set(required))
        if missing or extra:
            return {"status": "unsupported_input_schema", "message": "The supplied fields do not match the model's input schema.",
                    "missing_features": missing, "unexpected_features": extra, "required_features": required}
        problems = []
        for f in required:
            v = features[f]
            if f == "url":
                if not isinstance(v, str) or not v.strip() or len(v) > MAX_URL_LENGTH:
                    problems.append(f"url must be a non-empty string up to {MAX_URL_LENGTH} characters")
            elif f == "type":
                if v not in PS_TYPES:
                    problems.append(f"type must be one of {PS_TYPES}")
            else:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    problems.append(f"{f} must be a finite number")
                    continue
                lo, hi = NUMERIC_RANGES.get(f, (-1e9, 1e9))            # V1-V28 are unbounded PCA components: only finiteness is enforced
                if not lo <= v <= hi:
                    problems.append(f"{f} must be between {lo:g} and {hi:g}")
        return {"status": "invalid_input", "message": "One or more values are not acceptable.", "problems": problems} if problems else None

    def predict(self, name: str, features: dict) -> dict:
        r = self.result(name)
        base = {"model": name}
        if not r.ready:
            return {**base, "status": "model_unavailable", "state": r.state, "message": r.detail}
        bad = self.validate_features(name, features)
        if bad:
            return {**base, **bad}
        try:
            data = store_schema.row(features) if name == "store_grocery" else {k: features[k] for k in r.metadata["input_features"]}
            row = pd.DataFrame([data])
            raw = float(r.pipeline.raw_score(row)[0])                     # one forward pass; the calibrator maps it to a probability
            p = float(min(1.0, max(0.0, r.pipeline.calibrator.predict([raw])[0])))
        except Exception as exc:                                       # never fabricate a score
            log.warning("ml prediction failed for %s: %s", name, type(exc).__name__)
            return {**base, "status": "prediction_failed", "message": "The model could not score this input."}
        if not math.isfinite(p):
            return {**base, "status": "prediction_failed", "message": "The model returned an invalid score."}
        thr = float(r.metadata["threshold"])
        return {**base, "status": "ok", "model_version": r.metadata["version"], "probability": round(p, 6), "raw_score": round(raw, 6),
                "threshold": thr, "flagged": p >= thr, "decision": "review" if p >= thr else "no_alert",
                "is_fixture": bool(r.metadata.get("is_fixture")), "experimental": bool(r.metadata.get("experimental")),
                "note": "An estimate that this input resembles the fraud/phishing in the training data. Not proof, and nothing is blocked automatically."}


def _public_metrics(m: dict | None) -> dict | None:
    if not m:
        return None
    keep = ("threshold", "test_rows", "support_legitimate", "support_fraud", "fraud_prevalence", "accuracy", "precision", "recall", "f1", "f2",
            "pr_auc", "roc_auc", "confusion_matrix", "false_positives", "false_negatives", "false_positive_rate", "false_negative_rate",
            "brier", "calibration_error_ece", "flagged_share", "warning")
    return {k: m.get(k) for k in keep if k in m}
