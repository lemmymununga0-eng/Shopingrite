"""`store_risk_v1`: a transparent rule engine that scores store orders for human review.

It is NOT machine learning and its score is NOT proof of fraud. Every point comes from a named rule with a plain-language
reason, and only from facts the store really holds (the order, the customer's own order and payment history). It does not
use device fingerprints or IP geolocation because the store does not collect them. The stored `features` are exactly the
inputs used, so an analyst can reproduce any score by hand.

Decision bands: score >= 60 'high', >= 30 'review', otherwise 'allow'. 'review' and 'high' open an investigation case.
"""
import json
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from ..config import Settings
from ..db.models import FraudAssessment, Order, PaymentAttempt, SecurityEvent, utcnow

ENGINE, VERSION = "store_risk", "v1"
LOCAL_UTC_OFFSET_HOURS = 2          # Zambia (CAT, UTC+2): "night" means the customer's night, not the server's
HIGH_AT, REVIEW_AT = 60, 30
NOTE = "Rule-based score for human review (store_risk_v1). Not machine learning and not proof of wrongdoing."

# Rules that existed before scoring: if one fires, a case is opened even when the total score stays low.
HARD_RULES = ("high_value", "bulk_quantity", "order_velocity", "repeated_rejections")


@dataclass
class Assessment:
    score: int
    decision: str
    reasons: list[dict] = field(default_factory=list)
    features: dict = field(default_factory=dict)

    @property
    def rules(self) -> list[str]:
        return [r["rule"] for r in self.reasons]


def _decision(score: int) -> str:
    return "high" if score >= HIGH_AT else "review" if score >= REVIEW_AT else "allow"


def compute(session, order: Order, s: Settings) -> Assessment:
    now = utcnow()
    me, others = Order.user_id == order.user_id, Order.id != order.id
    prior_orders = session.scalar(select(func.count()).select_from(Order).where(me, others, Order.created_at < order.created_at)) or 0
    prior_paid, avg_paid = session.execute(select(func.count(), func.coalesce(func.avg(Order.total_cents), 0)).where(
        me, others, Order.created_at < order.created_at, Order.payment_status == "paid", Order.currency == order.currency)).one()
    orders_last_hour = session.scalar(select(func.count()).select_from(Order).where(
        me, Order.created_at >= order.created_at - timedelta(hours=1), Order.created_at <= order.created_at)) or 0
    failed_24h = session.scalar(select(func.count()).select_from(PaymentAttempt).join(Order, PaymentAttempt.order_id == Order.id)
                                .where(me, PaymentAttempt.status == "failed", PaymentAttempt.created_at >= now - timedelta(hours=24))) or 0
    rejected_10m = session.scalar(select(func.count()).select_from(SecurityEvent).where(
        SecurityEvent.event_type == "order.checkout_rejected", SecurityEvent.actor_id == order.user_id,
        SecurityEvent.created_at >= now - timedelta(minutes=10))) or 0
    seen_address = 0
    if order.fulfilment == "delivery" and prior_orders:
        seen_address = session.scalar(select(func.count()).select_from(Order).where(
            me, others, Order.address_line == order.address_line, Order.city == order.city)) or 0
    max_line = max((i.quantity for i in order.items), default=0)
    local_hour = (order.created_at.hour + LOCAL_UTC_OFFSET_HOURS) % 24

    f = {"total_cents": order.total_cents, "currency": order.currency, "max_line_quantity": max_line,
         "orders_last_hour": orders_last_hour, "prior_orders": prior_orders, "prior_paid_orders": prior_paid,
         "average_paid_total_cents": int(avg_paid or 0), "failed_payments_24h": failed_24h,
         "rejected_checkouts_10m": rejected_10m, "delivery_address_seen_before": bool(seen_address),
         "fulfilment": order.fulfilment, "local_hour": local_hour, "payment_method": order.payment_method}

    reasons: list[dict] = []

    def hit(rule: str, points: int, text: str):
        reasons.append({"rule": rule, "points": points, "text": text})

    if order.total_cents >= s.order_high_value_cents:
        hit("high_value", 30, "Order total is at or above the high-value limit.")
    if max_line >= s.order_bulk_quantity:
        hit("bulk_quantity", 15, "A line quantity is at or above the bulk-quantity limit.")
    if orders_last_hour >= s.order_velocity_per_hour:
        hit("order_velocity", 20, "The customer placed many orders within one hour.")
    if rejected_10m >= s.order_rejection_burst:
        hit("repeated_rejections", 20, "The customer had many rejected checkouts in the last 10 minutes.")
    if prior_paid == 0 and order.total_cents >= s.order_high_value_cents // 2:
        hit("first_order_large", 15, "This is the customer's first paid order and it is large.")
    if prior_paid >= 2 and avg_paid and order.total_cents >= 4 * float(avg_paid) and order.total_cents >= 10_000:
        hit("spend_spike", 20, "The total is at least four times this customer's usual paid order.")
    if failed_24h >= 3:
        hit("failed_payments", 25, "Three or more failed payments by this customer in the last 24 hours.")
    elif failed_24h >= 2:
        hit("failed_payments", 10, "Two failed payments by this customer in the last 24 hours.")
    if order.fulfilment == "delivery" and prior_orders and not seen_address:
        hit("new_address", 10, "Delivery to an address this customer has not used before.")
    if local_hour < 5:
        hit("night_order", 5, "Order placed between midnight and 05:00 local time.")

    score = min(100, sum(r["points"] for r in reasons))
    return Assessment(score=score, decision=_decision(score), reasons=reasons, features=f)


def save(session, order: Order, a: Assessment, trigger: str) -> FraudAssessment:
    row = FraudAssessment(order_id=order.id, engine=ENGINE, version=VERSION, trigger=trigger, score=a.score,
                          decision=a.decision, reasons_json=json.dumps(a.reasons), features_json=json.dumps(a.features))
    session.add(row)
    session.flush()
    return row


def latest(session, order_id: str) -> FraudAssessment | None:
    return session.scalar(select(FraudAssessment).where(FraudAssessment.order_id == order_id)
                          .order_by(FraudAssessment.created_at.desc(), FraudAssessment.id.desc()).limit(1))


def out(row: FraudAssessment) -> dict:
    return {"id": row.id, "engine": f"{row.engine}_{row.version}", "trigger": row.trigger, "score": row.score,
            "decision": row.decision, "reasons": json.loads(row.reasons_json), "features": json.loads(row.features_json),
            "created_at": row.created_at, "note": NOTE}
