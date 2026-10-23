"""Order risk: runs the `store_risk_v1` rule engine (services/store_risk.py) on an order, stores the assessment, and
opens an investigation case when a person should look.

These are plain, documented rules, NOT machine learning and NOT proof of fraud. Customer checkout never calls the
trained fraud model: ordinary retail fields do not match its feature contract (no device or country signal exists).
"""
import json
import logging

from sqlalchemy import select

from ..config import Settings
from ..db.models import Order
from . import ml_scoring, store_risk

log = logging.getLogger("fraudguard")
from .investigation_service import ensure_case

RULES = {
    "high_value": "Order total is at or above the high-value limit.",
    "bulk_quantity": "A line quantity is at or above the bulk-quantity limit.",
    "order_velocity": "The customer placed many orders within one hour.",
    "repeated_rejections": "The customer had many rejected checkouts in the last 10 minutes.",
}


def evaluate(db, events, s: Settings, order_id: str, correlation_id: str | None = None,
             trigger: str = "order_placed") -> list[str]:
    """Run after the order (or payment result) has committed. Stores one assessment and returns the names of the rules
    that fired. A case is opened for a 'review'/'high' decision or when any of the original hard rules fired."""
    with db.session() as session:
        order = session.scalar(select(Order).where(Order.id == order_id))
        if order is None:
            return []
        a = store_risk.compute(session, order, s)
        try:
            ml_rows = ml_scoring.record_for_order(session, getattr(db, "ml", None), order, trigger, a.features)
        except Exception:                               # model bookkeeping must never break checkout
            log.exception("ml result could not be recorded for order %s", order_id)
            ml_rows = []
        ml_alert = ml_scoring.alert_worthy(ml_rows)
        previous = store_risk.latest(session, order.id)
        if previous is not None and previous.score == a.score and previous.reasons_json == json.dumps(a.reasons):
            return a.rules                      # nothing changed since the last assessment: do not add noise
        store_risk.save(session, order, a, trigger)
        reference, user_id, total, currency = order.reference, order.user_id, order.total_cents, order.currency
    needs_case = a.decision != "allow" or any(r in store_risk.HARD_RULES for r in a.rules) or ml_alert
    if not needs_case:
        return a.rules
    summary = (f"Order {reference} scored {a.score}/100 ({a.decision}) by store_risk_v1: "
               + "; ".join(r["text"] for r in a.reasons))
    severity = "high" if a.decision == "high" or len(a.rules) >= 2 else "medium"
    events.record(severity, "order", "order.anomaly", summary[:500], actor_id=user_id, correlation_id=correlation_id,
                  details={"order_id": order_id, "rules": a.rules, "score": a.score, "decision": a.decision,
                           "total_cents": total, "currency": currency})
    with db.session() as session:
        ensure_case(session, source_type="order_anomaly", source_record_id=order_id, severity=severity,
                    summary=summary, evidence_reference=f"order:{order_id}", correlation_id=correlation_id)
    return a.rules
