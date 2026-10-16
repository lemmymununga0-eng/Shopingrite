from fastapi import APIRouter, Depends, Request

from ..auth import User, current_user
from ..dependencies import get_predictor
from ..ml import feature_schema as fs
from ..ml.predict import Predictor

router = APIRouter()


@router.get("/health", tags=["system"])
def health(request: Request, predictor: Predictor = Depends(get_predictor)):
    s = request.app.state.settings
    return {
        "status": "ok",
        "model_loaded": predictor.available,
        "mode": "REAL_MODEL" if predictor.available else "MODEL_UNAVAILABLE",
        "db_backend": s.db_backend,
        "auth_configured": bool(s.supabase_jwt_secret or s.supabase_url),
    }


@router.get("/model-info", tags=["system"])
def model_info(request: Request, predictor: Predictor = Depends(get_predictor), user: User = Depends(current_user)):
    s = request.app.state.settings
    base = {"features": fs.FEATURES, "risk_bands": {"high": s.risk_high, "medium": s.risk_medium}}
    if not predictor.available:
        return {**base, "trained": False, "mode": "MODEL_UNAVAILABLE", "message": predictor.error}
    m = predictor.metadata
    return {**base, "trained": True, "mode": "REAL_MODEL", "version": m["version"],
            "trained_at": m["trained_at"], "data_source": m["data_source"], "is_synthetic": m["is_synthetic"],
            "n_rows": m["n_rows"], "threshold": m["threshold"], "metrics": m["metrics"],
            "global_feature_importance": predictor.global_importance(),
            "importance_note": "Global importance across the training data. It does not explain any single prediction."}
