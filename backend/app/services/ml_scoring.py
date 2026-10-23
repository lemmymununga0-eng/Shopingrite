"""Records what the trained models can say about a store order, honestly.

The store collects ordinary retail fields (total, items, delivery, payment method). The card model needs anonymised PCA
components V1-V28 and the PaySim model needs account balances, which a grocery store does not have and must not invent.
So the recorded result is normally `unsupported_input_schema` with the missing field names, and NO score. If a model's
inputs ever do match, a genuine prediction is stored with its version and threshold.

Policy: an alert is raised from a model result only when status == 'ok', it is flagged, and the model is not experimental. Unsupported or unavailable results
never create alerts. The rule engine store_risk_v1 remains the basis for store decisions.
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db.models import MlPrediction, Order, PaymentAttempt

log = logging.getLogger("fraudguard")
STORE_MODELS = ("store_grocery", "creditcard_pca")      # the supported store model, and the research model (always unsupported here)


def record_for_order(session, ml, order: Order, trigger: str, features: dict) -> list[MlPrediction]:
    """Idempotent per (order, trigger, latest payment reference, model). Returns the rows for this event."""
    if ml is None:
        return []
    ref = session.scalar(select(PaymentAttempt.reference).where(PaymentAttempt.order_id == order.id)
                         .order_by(PaymentAttempt.id.desc()).limit(1)) or ""
    # `features` is the exact store_risk snapshot (store_schema grocery_txn_v1). It is never padded or reshaped for a model:
    # a model whose inputs differ (the research card model) answers unsupported_input_schema.
    rows = []
    for name in STORE_MODELS:
        existing = session.scalar(select(MlPrediction).where(
            MlPrediction.order_id == order.id, MlPrediction.trigger == trigger,
            MlPrediction.payment_ref == ref, MlPrediction.model == name))
        if existing is not None:
            rows.append(existing)
            continue
        res = ml.predict(name, features)
        row = MlPrediction(order_id=order.id, trigger=trigger, payment_ref=ref, model=name, status=res["status"],
                           model_version=res.get("model_version"), probability=res.get("probability"),
                           threshold=res.get("threshold"), flagged=res.get("flagged"), experimental=bool(res.get("experimental")),
                           missing_features_json=json.dumps(res.get("missing_features", [])))
        try:
            with session.begin_nested():
                session.add(row)
        except IntegrityError:                          # a concurrent replay won the race: keep one row
            row = session.scalar(select(MlPrediction).where(
                MlPrediction.order_id == order.id, MlPrediction.trigger == trigger,
                MlPrediction.payment_ref == ref, MlPrediction.model == name))
        rows.append(row)
    return rows


def public_view(row: MlPrediction) -> dict:
    return {"model": row.model, "status": row.status, "model_version": row.model_version, "probability": row.probability,
            "threshold": row.threshold, "flagged": row.flagged, "missing_features": json.loads(row.missing_features_json or "[]"),
            "trigger": row.trigger, "experimental": row.experimental,
            "event_id": f"{row.order_id}:{row.trigger}:{row.payment_ref or '-'}", "created_at": row.created_at.isoformat() if row.created_at else None}


def alert_worthy(rows: list[MlPrediction]) -> bool:
    return any(r.status == "ok" and r.flagged and not r.experimental for r in rows)
