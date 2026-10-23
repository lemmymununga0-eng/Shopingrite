"""Order creation, payment attempts, stock reservation and order states.

Safety properties (each is covered by a test):
  * All lines of an order are reserved in ONE database transaction. If any line cannot be reserved the whole
    transaction is rolled back, so a failed order never leaves stock partly deducted.
  * Stock is reduced with a single conditional statement (`... WHERE available_quantity >= :q`), so two checkouts
    racing for the last unit cannot both succeed, on SQLite or PostgreSQL. Every change is written to the stock ledger.
  * Prices and stock come from the database at checkout time, never from the client. Orders store snapshots.
  * An order is created 'awaiting_payment'. Only a succeeded payment attempt makes it 'confirmed'/'paid'. A failed or
    cancelled attempt never becomes successful by itself; a finished attempt is never changed again.
  * Stock hold policy: units stay reserved while an order awaits payment or after a failed attempt (so the customer can
    retry) until `payment_due_at` (PAYMENT_HOLD_MINUTES). After that the order is cancelled ('payment_expired') and the
    units go back on sale. Cancelling an order releases its stock immediately.
  * The same Idempotency-Key returns the same order instead of creating a second one.
  * This module never calls the fraud model and never touches payment credentials; no schema field can carry them.
"""
import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..db.models import (Cart, CartItem, IdempotencyKey, Inventory, Order, OrderItem, OrderStatusHistory, PaymentAttempt,
                         Product, effective_price_cents, new_id, utcnow)
from ..schemas.store import OrderCreate, OrderItemOut, OrderOut, PaymentAttemptOut, PaymentChoice
from . import notifications
from . import payment_service as pay
from .audit import record_audit
from .cart_service import delivery_fee, get_or_create_cart
from .stock_ledger import record_movement

CANCELLABLE = ("awaiting_payment", "payment_failed", "confirmed", "picking", "ready")
# Transitions a person (customer or administrator) may request. Payment-driven moves are in _SYSTEM below.
TRANSITIONS = {
    "awaiting_payment": {"cancelled"},
    "payment_failed": {"cancelled"},
    "confirmed": {"picking", "cancelled"},
    "picking": {"ready", "cancelled"},
    "ready": {"out_for_delivery", "completed", "cancelled"},
    "out_for_delivery": {"completed"},
}
_SYSTEM = {
    "awaiting_payment": {"confirmed", "payment_failed", "cancelled"},
    "payment_failed": {"awaiting_payment", "confirmed", "cancelled"},
}
TERMINAL_ATTEMPT = ("succeeded", "failed", "cancelled")
MAX_ATTEMPTS = 5


class CheckoutRejected(Exception):
    """The order cannot be placed (stock, availability or currency). Carries user-readable problems."""

    def __init__(self, problems: list[dict]):
        super().__init__("checkout rejected")
        self.problems = problems


def attempt_out(a: PaymentAttempt) -> PaymentAttemptOut:
    return PaymentAttemptOut(reference=a.reference, method=a.method, provider=a.provider, mode=a.mode, status=a.status,
                             amount_cents=a.amount_cents, currency=a.currency, failure_reason=a.failure_reason,
                             created_at=a.created_at, updated_at=a.updated_at)


def order_out(o: Order, attempts: list[PaymentAttempt] | None = None) -> OrderOut:
    if attempts is None:
        attempts = []
    return OrderOut(
        id=o.id, reference=o.reference, user_id=o.user_id, status=o.status, fulfilment=o.fulfilment,
        contact_name=o.contact_name, contact_email=o.contact_email, contact_phone=o.contact_phone,
        address_line=o.address_line, city=o.city, postal_code=o.postal_code, area=o.area,
        delivery_instructions=o.delivery_instructions,
        items=[OrderItemOut(product_id=i.product_id, sku=i.sku, name=i.name_snapshot, unit_price_cents=i.unit_price_cents,
                            quantity=i.quantity, line_total_cents=i.line_total_cents) for i in o.items],
        subtotal_cents=o.subtotal_cents, delivery_fee_cents=o.delivery_fee_cents, total_cents=o.total_cents,
        currency=o.currency, payment_mode=o.payment_mode, payment_method=o.payment_method,
        payment_status=o.payment_status, payment_due_at=o.payment_due_at, payment_notice=pay.notice_for(o.payment_mode),
        payment_attempts=[attempt_out(a) for a in attempts], created_at=o.created_at, updated_at=o.updated_at)


def order_view(session: Session, o: Order) -> OrderOut:
    attempts = session.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == o.id)
                               .order_by(PaymentAttempt.created_at, PaymentAttempt.reference)).all()
    return order_out(o, list(attempts))


def _validate_fulfilment(payload: OrderCreate, s: Settings):
    if payload.fulfilment == "delivery":
        if payload.address is None:
            raise HTTPException(422, "A delivery address is required for delivery orders.")
        cities = {c.lower() for c in s.city_list}
        if payload.address.city.lower() not in cities:
            raise HTTPException(422, f"We do not deliver to {payload.address.city} yet. Delivery areas: "
                                     f"{', '.join(s.city_list)}. You can choose collection instead.")


def _status_change(session: Session, order: Order, new_status: str, *, actor_id=None, reason="", system=False) -> None:
    """Guarded UPDATE (compare-and-set on the old status) plus a history row."""
    old = order.status
    table = _SYSTEM if system else TRANSITIONS
    if new_status not in table.get(old, set()):
        raise HTTPException(409, f"An order that is '{old}' cannot become '{new_status}'.")
    if session.execute(update(Order).where(Order.id == order.id, Order.status == old).values(status=new_status)).rowcount != 1:
        raise HTTPException(409, "The order was changed by someone else. Reload and try again.")
    session.add(OrderStatusHistory(order_id=order.id, from_status=old, to_status=new_status, actor_id=actor_id,
                                   reason=reason[:120]))
    session.flush()
    session.refresh(order)
    notifications.queue_status(session, order, new_status)


def _release(session: Session, order: Order, *, restock: bool, reason: str, actor_id=None):
    """Cancel/expiry: reserved units go back on sale. Completion: reserved units simply leave."""
    for it in order.items:
        da = it.quantity if restock else 0
        session.execute(update(Inventory).where(Inventory.product_id == it.product_id).values(
            available_quantity=Inventory.available_quantity + da,
            reserved_quantity=Inventory.reserved_quantity - it.quantity))
        record_movement(session, product_id=it.product_id, delta_available=da, delta_reserved=-it.quantity,
                        reason=reason, order_id=order.id, actor_id=actor_id)


def _cancel(session: Session, order: Order, *, actor_id, reason: str, stock_reason: str, system=False):
    was_paid = order.payment_status == "paid"
    _status_change(session, order, "cancelled", actor_id=actor_id, reason=reason, system=system)
    _release(session, order, restock=True, reason=stock_reason, actor_id=actor_id)
    # A paid order that is cancelled needs a refund. No refund workflow exists, so it is flagged for a person to handle.
    # Simulated payments moved no money, so there is nothing to refund.
    order.payment_status = ("refund_pending" if was_paid and order.payment_mode != "SIMULATED"
                            else "cancelled" if order.payment_status in ("paid", "pending", "requires_action", "failed", "cod_due") else order.payment_status)
    session.flush()


# ---------------------------------------------------------------- payments
def apply_outcome(session: Session, order: Order, attempt: PaymentAttempt, outcome: str, *, actor_id=None,
                  failure_reason: str = "", correlation_id=None) -> bool:
    """Apply a provider result to an attempt and its order. Returns False when it changed nothing (the attempt was
    already finished), so a repeated or late callback can never flip an outcome."""
    if attempt.status in TERMINAL_ATTEMPT:
        return False
    before = {"attempt": attempt.status, "order_status": order.status, "payment_status": order.payment_status}
    attempt.status = outcome
    if failure_reason:
        attempt.failure_reason = failure_reason[:200]
    if outcome == "succeeded":
        if order.status in ("awaiting_payment", "payment_failed"):
            order.payment_status, order.payment_due_at = "paid", None
            _status_change(session, order, "confirmed", reason="payment succeeded", system=True)
        else:   # money arrived for an order that is already cancelled/expired: keep the money visible, flag for a refund
            order.payment_status = "refund_pending"
    elif outcome == "failed":
        order.payment_status = "failed"
        if order.status == "awaiting_payment":
            _status_change(session, order, "payment_failed", reason="payment failed", system=True)
    elif outcome == "cancelled":
        order.payment_status = "cancelled"
        if order.status == "awaiting_payment":
            _status_change(session, order, "payment_failed", reason="payment cancelled by customer", system=True)
    elif outcome in ("pending", "requires_action"):
        order.payment_status = outcome
        if order.status == "payment_failed":
            _status_change(session, order, "awaiting_payment", reason="payment retry", system=True)
    session.flush()
    record_audit(session, actor=None, action=f"payment.{outcome}", entity_type="payment", entity_id=attempt.reference,
                 before=before, after={"order": order.reference, "order_status": order.status,
                                       "payment_status": order.payment_status}, correlation_id=correlation_id)
    return True


def settle_verification(session: Session, order: Order, attempt: PaymentAttempt, v, correlation_id=None) -> str:
    """Apply a result that Flutterwave's API has verified. Returns one of:
    succeeded | failed | pending | mismatch | unchanged.

    Money is never credited unless the verified reference, currency and amount match this attempt. A payment that
    arrives after the attempt was cancelled or failed is still honoured (the customer really paid): if the order is
    still open it is confirmed, otherwise it is flagged 'refund_pending' for staff. Repeated calls are harmless."""
    if v.state == "successful":
        expected = Decimal(attempt.amount_cents) / 100
        if v.tx_ref != attempt.reference or v.currency != attempt.currency or v.amount < expected:
            record_audit(session, actor=None, action="payment.amount_mismatch", entity_type="payment",
                         entity_id=attempt.reference,
                         after={"expected": str(expected), "expected_currency": attempt.currency, "got": str(v.amount),
                                "got_currency": v.currency, "flutterwave_id": v.transaction_id},
                         correlation_id=correlation_id)
            if attempt.status not in TERMINAL_ATTEMPT:
                apply_outcome(session, order, attempt, "failed",
                              failure_reason="The amount or currency paid did not match the order. Staff will review.",
                              correlation_id=correlation_id)
            return "mismatch"
        attempt.provider_reference = v.transaction_id[:64]
        if attempt.status == "succeeded":
            return "unchanged"
        if attempt.status in ("failed", "cancelled"):       # paid after we had given up on this attempt
            attempt.status, attempt.failure_reason = "pending", ""
            record_audit(session, actor=None, action="payment.late_success", entity_type="payment",
                         entity_id=attempt.reference, after={"order": order.reference, "order_status": order.status},
                         correlation_id=correlation_id)
        apply_outcome(session, order, attempt, "succeeded", correlation_id=correlation_id)
        return "succeeded"
    if v.state == "failed":
        if attempt.status in TERMINAL_ATTEMPT:
            return "unchanged"
        apply_outcome(session, order, attempt, "failed", failure_reason=v.processor_response or "The payment was declined.",
                      correlation_id=correlation_id)
        return "failed"
    return "pending"


def start_payment(session: Session, order: Order, choice: PaymentChoice, s: Settings, correlation_id=None) -> PaymentAttempt:
    """Create a payment attempt for an order and let the provider answer. Used at checkout and for retries."""
    provider = pay.provider_for(choice.method, s)
    attempt = PaymentAttempt(reference=pay.new_payment_reference(), order_id=order.id, method=choice.method,
                             provider=provider.name, mode=provider.mode, amount_cents=order.total_cents,
                             currency=order.currency, status="initiated")
    session.add(attempt)
    order.payment_method, order.payment_mode = choice.method, provider.mode
    session.flush()
    result = provider.initiate(reference=attempt.reference, amount_cents=attempt.amount_cents, currency=attempt.currency,
                               scenario=choice.scenario)
    attempt.provider_reference = result.provider_reference
    if choice.method == "cod":      # nothing to confirm online: the order proceeds, payment is collected on delivery
        attempt.status, order.payment_status, order.payment_due_at = "pending", "cod_due", None
        _status_change(session, order, "confirmed", reason="cash on delivery", system=True)
        record_audit(session, actor=None, action="payment.cod_selected", entity_type="payment",
                     entity_id=attempt.reference, after={"order": order.reference}, correlation_id=correlation_id)
    else:
        apply_outcome(session, order, attempt, result.status, failure_reason=result.failure_reason,
                      correlation_id=correlation_id)
    return attempt


def retry_payment(session: Session, user, order: Order, choice: PaymentChoice, s: Settings, correlation_id=None):
    if order.status not in ("awaiting_payment", "payment_failed"):
        raise HTTPException(409, f"This order is '{order.status}' and does not need payment.")
    attempts = session.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id)).all()
    if any(a.status in ("pending", "requires_action") for a in attempts):
        raise HTTPException(409, "A payment is already in progress for this order. Finish or cancel it first.")
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(409, "Too many payment attempts for this order. Please start a new order.")
    if order.payment_due_at is not None and order.payment_due_at < utcnow():
        raise HTTPException(409, "The payment window for this order has ended.")
    attempt = start_payment(session, order, choice, s, correlation_id)
    record_audit(session, actor=user, action="payment.retry", entity_type="order", entity_id=order.id,
                 after={"payment_reference": attempt.reference, "method": choice.method}, correlation_id=correlation_id)
    return attempt


def expire_unpaid_orders(session: Session, now=None) -> int:
    """Cancel orders whose payment window ended and put their stock back on sale. Idempotent."""
    now = now or utcnow()
    due = session.scalars(select(Order).where(Order.status.in_(("awaiting_payment", "payment_failed")),
                                              Order.payment_due_at.is_not(None), Order.payment_due_at < now)
                          .options(joinedload(Order.items))).unique().all()
    for order in due:
        for a in session.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id,
                                                              PaymentAttempt.status.in_(("initiated", "pending", "requires_action")))):
            a.status, a.failure_reason = "cancelled", "Payment window expired"
        _cancel(session, order, actor_id=None, reason="payment_expired", stock_reason="order_expired", system=True)
        record_audit(session, actor=None, action="order.payment_expired", entity_type="order", entity_id=order.id,
                     after={"reference": order.reference})
    return len(due)


# ---------------------------------------------------------------- orders
def create_order(session: Session, user, payload: OrderCreate, s: Settings, correlation_id: str | None = None,
                 idempotency_key: str | None = None) -> tuple[Order, bool]:
    """Runs inside the caller's transaction. Returns (order, replayed). Raises CheckoutRejected / HTTPException /
    PaymentUnavailable; the caller rolls back."""
    request_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    if idempotency_key:
        prior = session.scalar(select(IdempotencyKey).where(IdempotencyKey.user_id == user.id,
                                                            IdempotencyKey.key == idempotency_key))
        if prior is not None:
            if prior.request_hash != request_hash:
                raise HTTPException(422, "This Idempotency-Key was already used for a different request.")
            return get_order(session, prior.order_id), True
    _validate_fulfilment(payload, s)
    pay.provider_for(payload.payment.method, s)               # refuse a blocked/disabled method before touching stock
    expire_unpaid_orders(session)                             # units from abandoned orders are back on sale first
    cart = get_or_create_cart(session, user.id)
    items = session.scalars(select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.product_id)
                            .options(joinedload(CartItem.product))).unique().all()
    if not items:
        raise HTTPException(409, "Your cart is empty.")

    problems, lines, subtotal = [], [], 0
    for it in items:                         # ordered by product id: a consistent lock order avoids deadlocks
        p: Product = it.product
        if not p.is_active:
            problems.append({"product_id": p.id, "name": p.name, "requested": it.quantity, "available": 0,
                             "message": f"{p.name} is no longer available."})
            continue
        if p.currency != s.store_currency:
            problems.append({"product_id": p.id, "name": p.name, "requested": it.quantity, "available": 0,
                             "message": f"{p.name} is priced in {p.currency}; this store trades in {s.store_currency}."})
            continue
        if it.quantity > s.max_quantity_per_line:
            problems.append({"product_id": p.id, "name": p.name, "requested": it.quantity, "available": None,
                             "message": f"At most {s.max_quantity_per_line} of {p.name} per order."})
            continue
        reserved = session.execute(
            update(Inventory)
            .where(Inventory.product_id == p.id, Inventory.available_quantity >= it.quantity)
            .values(available_quantity=Inventory.available_quantity - it.quantity,
                    reserved_quantity=Inventory.reserved_quantity + it.quantity)).rowcount
        if reserved != 1:
            available = session.scalar(select(Inventory.available_quantity).where(Inventory.product_id == p.id)) or 0
            msg = (f"{p.name} is out of stock." if available <= 0
                   else f"Only {available} of {p.name} left; you asked for {it.quantity}.")
            problems.append({"product_id": p.id, "name": p.name, "requested": it.quantity, "available": available,
                             "message": msg})
            continue
        unit = effective_price_cents(p)
        lines.append((p, it.quantity, unit))
        subtotal += unit * it.quantity

    if problems:
        raise CheckoutRejected(problems)     # caller rolls back: reservations above are undone together

    fee = delivery_fee(subtotal, s) if payload.fulfilment == "delivery" else 0
    delivering = payload.fulfilment == "delivery" and payload.address is not None
    order_id, ref = new_id(), "ORD-" + secrets.token_hex(4).upper()
    order = Order(id=order_id, reference=ref, user_id=user.id, status="awaiting_payment", fulfilment=payload.fulfilment,
                  contact_name=payload.contact.name, contact_email=payload.contact.email,
                  contact_phone=payload.contact.phone,
                  address_line=payload.address.line if delivering else "", city=payload.address.city if delivering else "",
                  postal_code=payload.address.postal_code if delivering else "",
                  area=(payload.area or "") if delivering else "",
                  delivery_instructions=(payload.delivery_instructions or "") if delivering else "",
                  subtotal_cents=subtotal, delivery_fee_cents=fee, total_cents=subtotal + fee, currency=s.store_currency,
                  payment_status="pending", payment_due_at=utcnow() + timedelta(minutes=s.payment_hold_minutes))
    for p, qty, unit in lines:
        order.items.append(OrderItem(product_id=p.id, sku=p.sku, name_snapshot=p.name, unit_price_cents=unit,
                                     quantity=qty, line_total_cents=unit * qty))
        record_movement(session, product_id=p.id, delta_available=-qty, delta_reserved=qty, reason="order_reserved",
                        order_id=order_id, actor_id=user.id)
    session.add(order)
    session.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    session.flush()
    session.add(OrderStatusHistory(order_id=order_id, from_status="", to_status="awaiting_payment", actor_id=user.id,
                                   reason="order placed"))
    record_audit(session, actor=user, action="inventory.reserved", entity_type="order", entity_id=order.id,
                 after={"reference": ref, "lines": [{"sku": p.sku, "quantity": q} for p, q, _ in lines]},
                 correlation_id=correlation_id)
    record_audit(session, actor=user, action="order.created", entity_type="order", entity_id=order.id,
                 after={"reference": ref, "total_cents": order.total_cents, "currency": order.currency,
                        "fulfilment": order.fulfilment, "payment_method": payload.payment.method},
                 correlation_id=correlation_id)
    start_payment(session, order, payload.payment, s, correlation_id)
    if idempotency_key:
        session.add(IdempotencyKey(user_id=user.id, key=idempotency_key, request_hash=request_hash, order_id=order_id))
    session.flush()
    session.refresh(order)
    return order, False


def get_order(session: Session, order_id: str) -> Order | None:
    return session.execute(select(Order).where(Order.id == order_id).options(joinedload(Order.items))).unique().scalar_one_or_none()


def change_status(session: Session, user, order: Order, new_status: str, correlation_id=None) -> Order:
    """A person changes the status (cancel by owner/admin, fulfilment steps by admin)."""
    old = order.status
    if new_status == "cancelled":
        _cancel(session, order, actor_id=user.id, reason="cancelled by " + ("staff" if user.has("orders.manage") else "customer"),
                stock_reason="order_cancelled")
    else:
        _status_change(session, order, new_status, actor_id=user.id, reason="fulfilment update")
        if new_status == "completed":
            _release(session, order, restock=False, reason="order_completed", actor_id=user.id)
    record_audit(session, actor=user, action=f"order.{new_status}", entity_type="order", entity_id=order.id,
                 before={"status": old}, after={"status": new_status, "restocked": new_status == "cancelled"},
                 correlation_id=correlation_id)
    session.flush()
    session.refresh(order)
    return order
