"""Order-risk rules. These are plain, documented rules, NOT machine learning and NOT proof of fraud.

A triggered rule records a security event and opens (or reuses) an investigation case so a person can look.
Customer checkout never calls the fraud model: ordinary retail fields do not match its feature contract.
"""
from datetime import timedelta

from sqlalchemy import func, select

from ..config import Settings
from ..db.models import Order, SecurityEvent, utcnow
from .investigation_service import ensure_case

RULES = {
    "high_value": "Order total is at or above the high-value limit.",
    "bulk_quantity": "A line quantity is at or above the bulk-quantity limit.",
    "order_velocity": "The customer placed many orders within one hour.",
    "repeated_rejections": "The customer had many rejected checkouts in the last 10 minutes.",
}


def evaluate(db, events, s: Settings, order_id: str, correlation_id: str | None = None) -> list[str]:
    """Run after the order has committed. Returns the names of triggered rules."""
    triggered: list[str] = []
    with db.session() as session:
        order = session.scalar(select(Order).where(Order.id == order_id))
        if order is None:
            return []
        if order.total_cents >= s.order_high_value_cents:
            triggered.append("high_value")
        if any(i.quantity >= s.order_bulk_quantity for i in order.items):
            triggered.append("bulk_quantity")
        hour_ago = utcnow() - timedelta(hours=1)
        recent = session.scalar(select(func.count()).select_from(Order).where(Order.user_id == order.user_id,
                                                                             Order.created_at >= hour_ago))
        if recent >= s.order_velocity_per_hour:
            triggered.append("order_velocity")
        ten_min = utcnow() - timedelta(minutes=10)
        rejected = session.scalar(select(func.count()).select_from(SecurityEvent).where(
            SecurityEvent.event_type == "order.checkout_rejected", SecurityEvent.actor_id == order.user_id,
            SecurityEvent.created_at >= ten_min))
        if rejected >= s.order_rejection_burst:
            triggered.append("repeated_rejections")
        reference, user_id, total, currency = order.reference, order.user_id, order.total_cents, order.currency
    if not triggered:
        return []
    summary = f"Order {reference} triggered review rules: " + "; ".join(RULES[r] for r in triggered)
    severity = "high" if len(triggered) >= 2 else "medium"
    events.record(severity, "order", "order.anomaly", summary, actor_id=user_id, correlation_id=correlation_id,
                  details={"order_id": order_id, "rules": triggered, "total_cents": total, "currency": currency})
    with db.session() as session:
        ensure_case(session, source_type="order_anomaly", source_record_id=order_id, severity=severity,
                    summary=summary, evidence_reference=f"order:{order_id}", correlation_id=correlation_id)
    return triggered
