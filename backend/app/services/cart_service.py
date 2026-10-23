"""Server-side shopping cart. Every read re-checks stock, so the cart can never show stale availability."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..db.models import Cart, CartItem, Inventory, Product
from ..schemas.store import CartLine, CartOut
from .inventory_service import product_out


def money(cents: int, currency: str) -> str:
    if currency == "ZMW":
        return f"K{cents / 100:,.2f}"          # Zambian kwacha is written K1,234.50
    return f"{currency} {cents / 100:,.2f}"


def get_or_create_cart(session: Session, user_id: str) -> Cart:
    cart = session.scalar(select(Cart).where(Cart.user_id == user_id))
    if cart:
        return cart
    try:
        with session.begin_nested():
            cart = Cart(user_id=user_id)
            session.add(cart)
            session.flush()
    except IntegrityError:               # another request created it first
        cart = session.scalar(select(Cart).where(Cart.user_id == user_id))
    return cart


def line_issue(product: Product, quantity: int) -> tuple[str | None, str | None]:
    available = product.inventory.available_quantity if product.inventory else 0
    if not product.is_active:
        return "unavailable", f"{product.name} is no longer available."
    if available <= 0:
        return "out_of_stock", f"{product.name} is out of stock."
    if quantity > available:
        return "quantity_exceeds_stock", f"Only {available} of {product.name} available; you have {quantity} in your cart."
    return None, None


def delivery_fee(subtotal_cents: int, s: Settings) -> int:
    if subtotal_cents <= 0 or subtotal_cents >= s.free_delivery_over_cents:
        return 0
    return s.delivery_fee_cents


def fee_note(s: Settings) -> str:
    return (f"Delivery costs {money(s.delivery_fee_cents, s.store_currency)}, free over "
            f"{money(s.free_delivery_over_cents, s.store_currency)}. Collection is free.")


def cart_view(session: Session, user_id: str, s: Settings) -> CartOut:
    cart = get_or_create_cart(session, user_id)
    rows = session.scalars(select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
                           .options(joinedload(CartItem.product).joinedload(Product.category),
                                    joinedload(CartItem.product).joinedload(Product.inventory))).unique().all()
    lines, subtotal, count = [], 0, 0
    for it in rows:
        p = it.product
        po = product_out(p)
        issue, msg = line_issue(p, it.quantity)
        total = po.effective_price_cents * it.quantity
        lines.append(CartLine(item_id=it.id, product=po, quantity=it.quantity, line_total_cents=total,
                              issue=issue, issue_message=msg))
        subtotal += total
        count += it.quantity
    return CartOut(items=lines, item_count=count, subtotal_cents=subtotal, currency=s.store_currency,
                   has_issues=any(l.issue for l in lines), delivery_fee_cents=delivery_fee(subtotal, s),
                   delivery_fee_note=fee_note(s))


def _check_quantity(product: Product, quantity: int, s: Settings):
    if quantity > s.max_quantity_per_line:
        raise HTTPException(409, f"You can order at most {s.max_quantity_per_line} of one item.")
    available = product.inventory.available_quantity if product.inventory else 0
    if available <= 0:
        raise HTTPException(409, f"{product.name} is out of stock.")
    if quantity > available:
        raise HTTPException(409, f"Only {available} of {product.name} available.")


def add_item(session: Session, user_id: str, product_id: int, quantity: int, s: Settings):
    product = session.scalar(select(Product).where(Product.id == product_id, Product.is_active.is_(True))
                             .options(joinedload(Product.inventory)))
    if product is None:
        raise HTTPException(404, "Product not found")
    if product.currency != s.store_currency:
        raise HTTPException(409, f"{product.name} is priced in {product.currency}, but this store trades in "
                                 f"{s.store_currency}.")
    cart = get_or_create_cart(session, user_id)
    item = session.scalar(select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product_id))
    new_qty = (item.quantity if item else 0) + quantity
    _check_quantity(product, new_qty, s)
    if item:
        item.quantity = new_qty
    else:
        session.add(CartItem(cart_id=cart.id, product_id=product_id, quantity=new_qty))
    session.flush()


def _owned_item(session: Session, user_id: str, item_id: int) -> CartItem:
    item = session.scalar(select(CartItem).join(Cart).where(CartItem.id == item_id, Cart.user_id == user_id)
                          .options(joinedload(CartItem.product).joinedload(Product.inventory)))
    if item is None:
        raise HTTPException(404, "Cart item not found")      # same answer for "missing" and "someone else's"
    return item


def update_item(session: Session, user_id: str, item_id: int, quantity: int, s: Settings):
    item = _owned_item(session, user_id, item_id)
    _check_quantity(item.product, quantity, s)
    item.quantity = quantity
    session.flush()


def remove_item(session: Session, user_id: str, item_id: int):
    item = _owned_item(session, user_id, item_id)
    session.delete(item)
    session.flush()
