"""Real-payment orchestration shared by the HTTP routes, the webhook and the background reconciler.

Pattern for every Flutterwave call: read what is needed in a short transaction, close it, make the network call, then
open a new transaction to write the result. A slow or failed HTTP call therefore never holds a database lock.
"""
import logging
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from ..db.models import Order, PaymentAttempt, PaymentEvent, utcnow
from . import notifications, order_risk, order_service
from . import payment_service as pay
from .audit import record_audit
from .flutterwave import FlutterwaveClient, FlutterwaveError

log = logging.getLogger("fraudguard")
RECONCILE_MIN_AGE = timedelta(seconds=90)      # give the customer and the webhook a chance first
RECONCILE_MAX_AGE = timedelta(days=3)
RECONCILE_CANCELLED_AGE = timedelta(hours=2)


def require_client(flw: FlutterwaveClient | None) -> FlutterwaveClient:
    if flw is None:
        raise HTTPException(503, "Online payments are not available right now.")
    return flw


def attempt_by_reference(session, reference: str) -> PaymentAttempt | None:
    return session.scalar(select(PaymentAttempt).where(PaymentAttempt.reference == reference))


def create_checkout_link(db, flw: FlutterwaveClient, settings, reference: str, user_id: str) -> str:
    """The hosted payment page for a pending attempt (created once, then reused). Owner only."""
    with db.session() as session:
        a = attempt_by_reference(session, reference)
        order = order_service.get_order(session, a.order_id) if a else None
        if a is None or order is None or order.user_id != user_id or a.provider != "flutterwave":
            raise HTTPException(404, "Payment not found")
        if a.status != "pending" or order.status not in ("awaiting_payment", "payment_failed"):
            raise HTTPException(409, "This payment can no longer be paid. Please check your order.")
        if a.checkout_url:
            return a.checkout_url
        args = dict(tx_ref=a.reference, amount_cents=a.amount_cents, currency=a.currency,
                    redirect_url=f"{settings.frontend_url.rstrip('/')}/shop/payment/{order.id}",
                    email=order.contact_email, name=order.contact_name, phone=order.contact_phone,
                    title=settings.store_name, payment_options=pay.FLW_OPTIONS.get(a.method, "card"))
    try:
        url = flw.create_link(**args)
    except FlutterwaveError as exc:
        with db.session() as session:      # a double click may have created the link a moment ago
            a = attempt_by_reference(session, reference)
            if a is not None and a.checkout_url:
                return a.checkout_url
        log.warning("flutterwave create_link failed for %s: %s", reference, exc)
        raise HTTPException(502, "The payment page could not be created. Please try again in a moment.")
    with db.session() as session:
        a = attempt_by_reference(session, reference)
        if not a.checkout_url:
            a.checkout_url = url
        return a.checkout_url


def reassess(db, events, settings, reference: str, correlation_id: str | None = None) -> None:
    """A failed or mismatched payment changes the order's risk (failed-payment counts). Never fails the payment flow."""
    if settings is None:
        return
    try:
        with db.session() as session:
            a = attempt_by_reference(session, reference)
            order_id = a.order_id if a else None
        if order_id:
            order_risk.evaluate(db, events, settings, order_id, correlation_id, trigger="payment_failed")
    except Exception:
        log.exception("risk re-assessment failed for %s", reference)


def _apply(db, v, reference: str, correlation_id, event) -> tuple[str, str]:
    """Write a verified result in one short transaction. Returns (outcome, text for a mismatch event)."""
    with db.session() as session:
        a = attempt_by_reference(session, reference)
        order = order_service.get_order(session, a.order_id)
        if event:
            session.add(PaymentEvent(attempt_id=a.id, provider="flutterwave", event_id=event["id"],
                                     outcome=event.get("outcome", "")[:16], signature_valid=True))
            try:
                session.flush()
            except IntegrityError:          # two deliveries of the same event raced
                session.rollback()
                return "duplicate", ""
        outcome = order_service.settle_verification(session, order, a, v, correlation_id)
        if event:
            ev = session.scalar(select(PaymentEvent).where(PaymentEvent.provider == "flutterwave",
                                                           PaymentEvent.event_id == event["id"]))
            ev.applied = outcome in ("succeeded", "failed")
        return outcome, f"{v.amount} {v.currency} for {a.amount_cents / 100:.2f} {a.currency}"


def verify_and_settle(db, flw: FlutterwaveClient, events, reference: str, correlation_id: str | None = None,
                      event: dict | None = None, settings=None) -> str:
    """Ask Flutterwave what happened to this attempt and apply it. `event` = {"id","outcome"} records a webhook
    delivery in the same transaction. Returns the settle outcome, 'unknown' for a reference we never issued, or
    'duplicate'. Raises FlutterwaveError when Flutterwave cannot be reached (callers decide whether to retry)."""
    with db.session() as session:
        a = attempt_by_reference(session, reference)
        if a is None or a.provider != "flutterwave":
            return "unknown"
        if event and session.scalar(select(PaymentEvent.id).where(PaymentEvent.provider == "flutterwave",
                                                                    PaymentEvent.event_id == event["id"])):
            return "duplicate"
    v = flw.verify_by_reference(reference)
    try:
        outcome, mismatch_detail = _apply(db, v, reference, correlation_id, event)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        return "unchanged"       # the webhook and the customer's return settled it at the same moment: the other one won
    if outcome == "mismatch":                # recorded after the transaction closed (see order_service notes)
        events.record("high", "provider", "payment.amount_mismatch",
                      f"Flutterwave reports {mismatch_detail} for {reference}: review before fulfilling.",
                      correlation_id=correlation_id)
    if outcome in ("failed", "mismatch"):
        reassess(db, events, settings, reference, correlation_id)
    return outcome


def cancel_attempt(db, flw: FlutterwaveClient, events, reference: str, user_id: str, correlation_id: str | None = None,
                   settings=None) -> str:
    """The customer leaves the hosted page without paying. Verify first (they may have paid a moment ago); only if
    Flutterwave shows no successful payment is the attempt cancelled, so a retry becomes possible."""
    with db.session() as session:
        a = attempt_by_reference(session, reference)
        order = order_service.get_order(session, a.order_id) if a else None
        if a is None or order is None or order.user_id != user_id or a.provider != "flutterwave":
            raise HTTPException(404, "Payment not found")
    outcome = verify_and_settle(db, flw, events, reference, correlation_id, settings=settings)
    if outcome in ("succeeded", "mismatch", "unchanged"):
        return outcome
    with db.session() as session:
        a = attempt_by_reference(session, reference)
        order = order_service.get_order(session, a.order_id)
        if order_service.apply_outcome(session, order, a, "cancelled", actor_id=user_id,
                                       failure_reason="You cancelled the payment.", correlation_id=correlation_id):
            return "cancelled"
    return "unchanged"


def reconcile_pending(db, flw: FlutterwaveClient, events, limit: int = 50, settings=None) -> int:
    """Safety net for lost webhooks and customers who closed the tab: check recent pending attempts (and recently
    cancelled ones, in case the customer paid after the stock hold expired). Returns how many
    changed. Errors for one attempt never stop the others."""
    now = utcnow()
    with db.session() as session:
        refs = list(session.scalars(select(PaymentAttempt.reference).where(
            PaymentAttempt.provider == "flutterwave", PaymentAttempt.created_at < now - RECONCILE_MIN_AGE,
            or_(and_(PaymentAttempt.status == "pending", PaymentAttempt.created_at > now - RECONCILE_MAX_AGE),
                # attempts cancelled when the stock hold expired: a customer may still have paid on the open page
                and_(PaymentAttempt.status == "cancelled", PaymentAttempt.provider_reference == "",
                     PaymentAttempt.created_at > now - RECONCILE_CANCELLED_AGE)))
            .order_by(PaymentAttempt.created_at).limit(limit)))
    changed = 0
    for ref in refs:
        try:
            if verify_and_settle(db, flw, events, ref, settings=settings) in ("succeeded", "failed", "mismatch"):
                changed += 1
        except FlutterwaveError as exc:
            log.warning("reconcile %s skipped: %s", ref, exc)
        except Exception:
            log.exception("reconcile %s failed", ref)
    return changed


def refund_order(db, flw: FlutterwaveClient, order_id: str, actor, correlation_id: str | None = None) -> dict:
    """Staff refund of a paid-then-cancelled order (status 'refund_pending'). Full amount, once."""
    with db.session() as session:
        order = order_service.get_order(session, order_id)
        if order is None:
            raise HTTPException(404, "Order not found")
        if order.payment_status != "refund_pending":
            raise HTTPException(409, f"This order's payment is '{order.payment_status}', not waiting for a refund.")
        a = session.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id,
                                                        PaymentAttempt.provider == "flutterwave",
                                                        PaymentAttempt.status == "succeeded"))
        if a is None or not a.provider_reference:
            raise HTTPException(409, "No verified online payment is recorded for this order; refund it manually in "
                                     "the Flutterwave dashboard.")
        txn, reference, ref_order = a.provider_reference, a.reference, order.reference
        comments = f"Refund for order {order.reference}"
    try:
        data = flw.refund(txn, comments=comments)
    except FlutterwaveError as exc:
        raise HTTPException(502, str(exc))
    with db.session() as session:
        order = order_service.get_order(session, order_id)
        order.payment_status = "refunded"
        notifications.queue_refund(session, order)
        record_audit(session, actor=actor, action="payment.refunded", entity_type="payment", entity_id=reference,
                     after={"order": ref_order, "refund_status": str(data.get("status", ""))[:30],
                            "amount_refunded": str(data.get("amount_refunded", ""))}, correlation_id=correlation_id)
        return order_service.order_view(session, order).model_dump(mode="json")
