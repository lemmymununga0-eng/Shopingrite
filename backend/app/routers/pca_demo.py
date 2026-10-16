"""Approach A demonstration endpoints: the Kaggle PCA model (Time, V1-V28, Amount).

Separate from /predict on purpose. Nothing here is saved to the transaction history and the payment form
does not use it.
"""
import math

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from ..auth import User, current_user
from ..dependencies import predict_rate_limit
from ..ml import pca_demo

router = APIRouter(prefix="/pca-demo", tags=["pca-demo"])


class PcaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, float]


def _model(request: Request):
    return request.app.state.pca


@router.get("/info")
def info(request: Request, user: User = Depends(current_user)):
    m = _model(request)
    base = {"label": "Kaggle PCA dataset demonstration (separate from the payment form)", "features": pca_demo.FEATURES}
    if not m.available:
        return {**base, "trained": False, "message": m.error}
    md = m.metadata
    return {**base, "trained": True, "version": md["version"], "trained_at": md["trained_at"],
            "data_source": md["data_source"], "source_note": md["source_note"], "n_rows": md["n_rows"],
            "cleaning": md["cleaning"], "threshold": md["threshold"], "metrics": md["metrics"]}


@router.post("/predict")
def predict(body: PcaRequest, request: Request, user: User = Depends(predict_rate_limit)):
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
