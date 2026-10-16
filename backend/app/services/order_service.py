"""Order creation and stock reservation.

Safety properties (each is covered by a test):
  * All lines of an order are reserved in ONE database transaction. If any line cannot be reserved the
    whole transaction is rolled back, so a failed order never leaves stock partly deducted.
  * Stock is reduced with a single conditional statement (`... WHERE available_quantity >= :q`), so two
    checkouts racing for the last unit cannot both succeed, on SQLite or PostgreSQL.
  * Orders store snapshots of names, prices and quantities.
  * Prices and stock come from the database at checkout time, never from the client.
  * This module never calls the fraud model and never touches payment credentials.
"""
import secrets

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..db.models import Cart, CartItem, Inventory, Order, OrderItem, Product
from ..schemas.store import OrderCreate, OrderItemOut, OrderOut
from .audit import record_audit
from .cart_service import delivery_fee, get_or_create_cart
from .payment_service import SimulatedPaymentAdapter, notice_for

CANCELLABLE = ("confirmed", "picking", "ready")
TRANSITIONS = {
    "confirmed": {"picking", "cancelled"},
    "picking": {"ready", "cancelled"},
    "ready": {"out_for_delivery", "completed", "cancelled"},
    "out_for_delivery": {"completed"},
}


class CheckoutRejected(Exception):
    """The order cannot be placed (stock, availability or currency). Carries user-readable problems."""

    def __init__(self, problems: list[dict]):
        super().__init__("checkout rejected")
        self.problems = problems


def order_out(o: Order) -> OrderOut:
    return OrderOut(
        id=o.id, reference=o.reference, user_id=o.user_id, status=o.status, fulfilment=o.fulfilment,
        contact_name=o.contact_name, contact_email=o.contact_email, contact_phone=o.contact_phone,
        address_line=o.address_line, city=o.city, postal_code=o.postal_code,
        items=[OrderItemOut(product_id=i.product_id, sku=i.sku, name=i.name_snapshot, unit_price_cents=i.unit_price_cents,
                            quantity=i.quantity, line_total_cents=i.line_total_cents) for i in o.items],
        subtotal_cents=o.subtotal_cents, delivery_fee_cents=o.delivery_fee_cents, total_cents=o.total_cents,
        currency=o.currency, payment_mode=o.payment_mode, payment_status=o.payment_status,
        payment_notice=notice_for(o.payment_mode), created_at=o.created_at, updated_at=o.updated_at)


def _validate_fulfilment(payload: OrderCreate, s: Settings):
    if payload.fulfilment == "delivery":
        if payload.address is None:
            raise HTTPException(422, "A delivery address is required for delivery orders.")
        cities = {c.lower() for c in s.city_list}
        if payload.address.city.lower() not in cities:
            raise HTTPException(422, f"We do not deliver to {payload.address.city} yet. Delivery areas: "
                                     f"{', '.join(s.city_list)}. You can choose collection instead.")


def create_order(session: Session, user, payload: OrderCreate, s: Settings, correlation_id: str | None = None) -> Order:
    """Runs inside the caller's transaction. Raises CheckoutRejected / HTTPException; the caller rolls back."""
    _validate_fulfilment(payload, s)
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
        unit = p.offer_price_cents if p.offer_price_cents is not None else p.price_cents
        lines.append((p, it.quantity, unit))
        subtotal += unit * it.quantity

    if problems:
        raise CheckoutRejected(problems)     # caller rolls back: reservations above are undone together

    fee = delivery_fee(subtotal, s) if payload.fulfilment == "delivery" else 0
    ref = "ORD-" + secrets.token_hex(4).upper()
    order = Order(reference=ref, user_id=user.id, status="confirmed", fulfilment=payload.fulfilment,
                  contact_name=payload.contact.name, contact_email=payload.contact.email,
                  contact_phone=payload.contact.phone,
                  address_line=payload.address.line if payload.fulfilment == "delivery" and payload.address else "",
                  city=payload.address.city if payload.fulfilment == "delivery" and payload.address else "",
                  postal_code=payload.address.postal_code if payload.fulfilment == "delivery" and payload.address else "",
                  subtotal_cents=subtotal, delivery_fee_cents=fee, total_cents=subtotal + fee, currency=s.store_currency)
    for p, qty, unit in lines:
        order.items.append(OrderItem(product_id=p.id, sku=p.sku, name_snapshot=p.name, unit_price_cents=unit,
                                     quantity=qty, line_total_cents=unit * qty))
    result = SimulatedPaymentAdapter().authorize(order_reference=ref, amount_cents=order.total_cents, currency=order.currency)
    order.payment_mode, order.payment_status = result.mode, result.status
    session.add(order)
    session.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    session.flush()
    record_audit(session, actor=user, action="inventory.reserved", entity_type="order", entity_id=order.id,
                 after={"reference": ref, "lines": [{"sku": p.sku, "quantity": q} for p, q, _ in lines]},
                 correlation_id=correlation_id)
    record_audit(session, actor=user, action="order.created", entity_type="order", entity_id=order.id,
                 after={"reference": ref, "total_cents": order.total_cents, "currency": order.currency,
                        "fulfilment": order.fulfilment, "payment_mode": order.payment_mode}, correlation_id=correlation_id)
    session.refresh(order)
    return order


def get_order(session: Session, order_id: str) -> Order | None:
    return session.execute(select(Order).where(Order.id == order_id).options(joinedload(Order.items))).unique().scalar_one_or_none()


def _release(session: Session, order: Order, *, restock: bool):
    """Return reserved units: back to available when cancelled, simply dropped from reserved when completed."""
    for it in order.items:
        values = {"reserved_quantity": Inventory.reserved_quantity - it.quantity}
        if restock:
            values["available_quantity"] = Inventory.available_quantity + it.quantity
        session.execute(update(Inventory).where(Inventory.product_id == it.product_id).values(**values))


def change_status(session: Session, user, order: Order, new_status: str, correlation_id=None) -> Order:
    """Atomic: the status row is changed with a guarded UPDATE so two racing requests cannot both restock."""
    old = order.status
    allowed_next = TRANSITIONS.get(old, set())
    if new_status not in allowed_next:
        raise HTTPException(409, f"An order that is '{old}' cannot become '{new_status}'.")
    changed = session.execute(update(Order).where(Order.id == order.id, Order.status == old)
                              .values(status=new_status)).rowcount
    if changed != 1:
        raise HTTPException(409, "The order was changed by someone else. Reload and try again.")
    if new_status == "cancelled":
        _release(session, order, restock=True)
    elif new_status == "completed":
        _release(session, order, restock=False)
    record_audit(session, actor=user, action=f"order.{new_status}", entity_type="order", entity_id=order.id,
                 before={"status": old}, after={"status": new_status, "restocked": new_status == "cancelled"},
                 correlation_id=correlation_id)
    session.flush()
    session.refresh(order)
    return order
