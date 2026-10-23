"""Verified-data model endpoints (staff only). Status and metrics are read from the saved artifact metadata, never hard-coded."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..auth import User, require
from ..dependencies import get_session, predict_rate_limit
from ..ml import store_dataset, store_schema
from ..ml.service import MODEL_NAMES

router = APIRouter(prefix="/fraud", tags=["fraud-models"])


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    features: dict[str, Any]


def _svc(request: Request):
    return request.app.state.ml


@router.get("/model-status")
def model_status(request: Request, user: User = Depends(require("fraud.view")), session=Depends(get_session)):
    models = _svc(request).all_status()
    store = next((m for m in models if m["model"] == "store_grocery"), {})
    labels = store_dataset.readiness(session)
    live_model = bool(store.get("ready"))
    return {"models": models, "any_ready": any(m["ready"] for m in models),
            "store_scoring": {
                "method": "supervised model (experimental, shadow mode)" if live_model and store.get("experimental") else
                          "supervised model" if live_model else "rules",
                "rule_engine": "store_risk_v1",
                "schema_version": store_schema.SCHEMA_VERSION,
                "message": ("Store orders are scored by the rule engine store_risk_v1. " + labels["message"]) if not live_model else
                           "Store orders are scored by store_risk_v1 and recorded against the store_grocery model."
                           + (" The model is EXPERIMENTAL: its results are recorded for comparison and never raise alerts." if store.get("experimental") else ""),
                "labels": labels},
            "research_models_note": "The card (V1-V28) model is a research model on public data and cannot score store orders."}


@router.get("/store-schema")
def store_feature_schema(user: User = Depends(require("fraud.view"))):
    """The versioned list of store fields a grocery model may use, with source, allowed values, missing-value handling and privacy notes."""
    return {"schema_version": store_schema.SCHEMA_VERSION, "features": store_schema.document(), "guards": store_schema.GUARD_SPECS,
            "excluded": [{"what": w, "why": y} for w, y in store_schema.EXCLUDED]}


@router.post("/predict")
def predict(body: PredictRequest, request: Request, user: User = Depends(predict_rate_limit),
            _allowed: User = Depends(require("fraud.predict"))):
    if body.model not in MODEL_NAMES:
        raise HTTPException(422, detail={"message": "Unknown model.", "available": list(MODEL_NAMES)})
    result = _svc(request).predict(body.model, dict(body.features))
    code = {"ok": 200, "unsupported_input_schema": 422, "invalid_input": 422, "model_unavailable": 503, "prediction_failed": 500}[result["status"]]
    if code != 200:
        raise HTTPException(code, detail=result)
    return {**result, "saved": False}
