"""Approach A demonstration endpoints: the Kaggle PCA model (Time, V1-V28, Amount).

Separate from /predict on purpose. Nothing here is saved to the transaction history and the payment form
does not use it.
"""
import math

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from ..auth import User, require
from ..dependencies import predict_rate_limit
from ..ml import pca_demo

router = APIRouter(prefix="/pca-demo", tags=["pca-demo"])


class PcaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, float]


def _model(request: Request):
    return request.app.state.pca


def _verified(request: Request):
    """The registry's creditcard_pca model (real data, validated, checksum-verified) when it is ready; otherwise None and the
    older single-file demo model is used."""
    ml = getattr(request.app.state, "ml", None)
    return ml if ml is not None and ml.result("creditcard_pca").ready else None


@router.get("/info")
def info(request: Request, user: User = Depends(require("fraud.view"))):
    m = _model(request)
    base = {"label": "Kaggle PCA dataset demonstration (separate from the payment form)", "features": pca_demo.FEATURES}
    ml = _verified(request)
    if ml is not None:
        st = ml.status("creditcard_pca")
        return {**base, "trained": True, "source": "verified registry model", "version": st["version"], "trained_at": st["trained_at"],
                "data_source": st["dataset"]["name"], "source_note": st["dataset"]["source"], "n_rows": st["split"]["train_rows"] + st["split"]["test_rows"],
                "threshold": st["threshold"], "metrics": st["test_metrics"], "is_fixture": st["is_fixture"]}
    if not m.available:
        return {**base, "trained": False, "message": m.error}
    md = m.metadata
    return {**base, "trained": True, "version": md["version"], "trained_at": md["trained_at"],
            "data_source": md["data_source"], "source_note": md["source_note"], "n_rows": md["n_rows"],
            "cleaning": md["cleaning"], "threshold": md["threshold"], "metrics": md["metrics"]}


@router.post("/predict")
def predict(body: PcaRequest, request: Request, user: User = Depends(predict_rate_limit),
            _allowed: User = Depends(require("fraud.predict"))):
    ml = _verified(request)
    if ml is not None:
        res = ml.predict("creditcard_pca", dict(body.features))
        if res["status"] != "ok":
            raise HTTPException(422 if res["status"] in ("unsupported_input_schema", "invalid_input") else 503, detail=res)
        p, thr = res["probability"], res["threshold"]
        return {**res, "prediction": int(res["flagged"]), "fraud_probability": p,
                "risk_level": "High" if p >= thr else "Medium" if p >= thr / 2 else "Low", "saved": False,
                "note": "Model estimate on anonymised PCA features. Not proof of fraud and not saved to history."}
    m = _model(request)
    if not m.available:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"PCA demo model unavailable: {m.error}")
    supplied = set(body.features)
    missing = [f for f in pca_demo.FEATURES if f not in supplied]
    extra = sorted(supplied - set(pca_demo.FEATURES))
    if missing or extra:
        raise HTTPException(422, detail={
            "message": "Feature names must match the trained model exactly.",
            "missing_features": missing, "unexpected_features": extra})
    if not all(math.isfinite(v) for v in body.features.values()):
        raise HTTPException(422, "All feature values must be finite numbers.")
    return {**m.predict(body.features), "saved": False,
            "note": "Model estimate on anonymised PCA features. Not proof of fraud and not saved to history."}
