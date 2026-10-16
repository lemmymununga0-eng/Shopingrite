"""Catalogue queries and stock helpers. Stock lives in the `inventory` table, never in the UI."""
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db.models import Category, Inventory, Product
from ..schemas.store import InventoryOut, ProductOut
from .audit import record_audit


def stock_status(available: int, reorder_threshold: int) -> str:
    if available <= 0:
        return "out_of_stock"
    return "low_stock" if available <= reorder_threshold else "in_stock"


def product_out(p: Product) -> ProductOut:
    inv = p.inventory
    available = inv.available_quantity if inv else 0
    threshold = inv.reorder_threshold if inv else 0
    effective = p.offer_price_cents if p.offer_price_cents is not None else p.price_cents
    return ProductOut(id=p.id, sku=p.sku, name=p.name, description=p.description, category_slug=p.category.slug,
                      category_name=p.category.name, price_cents=p.price_cents, offer_price_cents=p.offer_price_cents,
                      effective_price_cents=effective, currency=p.currency, unit=p.unit, image_ref=p.image_ref,
                      is_featured=p.is_featured, is_demo=p.is_demo, stock_status=stock_status(available, threshold),
                      available_quantity=max(available, 0))


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


SORTS = {
    "name": Product.name.asc(), "price_asc": func.coalesce(Product.offer_price_cents, Product.price_cents).asc(),
    "price_desc": func.coalesce(Product.offer_price_cents, Product.price_cents).desc(), "newest": Product.id.desc(),
}


def list_products(session: Session, *, search=None, category=None, min_price_cents=None, max_price_cents=None,
                  sort="name", in_stock_only=False, on_offer=False, featured=False, page=1, page_size=12):
    q = select(Product).where(Product.is_active.is_(True))
    if search:
        q = q.where(or_(Product.name.ilike(_like(search), escape="\\"), Product.description.ilike(_like(search), escape="\\"),
                        Product.sku.ilike(_like(search), escape="\\")))
    if category:
        q = q.join(Category).where(Category.slug == category)
    price = func.coalesce(Product.offer_price_cents, Product.price_cents)
    if min_price_cents is not None:
        q = q.where(price >= min_price_cents)
    if max_price_cents is not None:
        q = q.where(price <= max_price_cents)
    if on_offer:
        q = q.where(Product.offer_price_cents.is_not(None))
    if featured:
        q = q.where(Product.is_featured.is_(True))
    if in_stock_only:
        q = q.join(Inventory, Inventory.product_id == Product.id).where(Inventory.available_quantity > 0)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.options(joinedload(Product.category), joinedload(Product.inventory))
                           .order_by(SORTS.get(sort, SORTS["name"]), Product.id)
                           .limit(page_size).offset((page - 1) * page_size)).unique().all()
    return [product_out(p) for p in rows], total


def get_product(session: Session, product_id: int) -> Product:
    p = session.scalar(select(Product).where(Product.id == product_id, Product.is_active.is_(True))
                       .options(joinedload(Product.category), joinedload(Product.inventory)))
    if p is None:
        raise HTTPException(404, "Product not found")
    return p


def list_categories(session: Session):
    counts = dict(session.execute(select(Product.category_id, func.count()).where(Product.is_active.is_(True))
                                  .group_by(Product.category_id)).all())
    return [{"id": c.id, "slug": c.slug, "name": c.name, "product_count": counts.get(c.id, 0)}
            for c in session.scalars(select(Category).order_by(Category.sort_order, Category.name))]


def inventory_out(inv: Inventory) -> InventoryOut:
    return InventoryOut(product_id=inv.product_id, sku=inv.product.sku, name=inv.product.name,
                        category_slug=inv.product.category.slug, available_quantity=inv.available_quantity,
                        reserved_quantity=inv.reserved_quantity, reorder_threshold=inv.reorder_threshold,
                        stock_status=stock_status(inv.available_quantity, inv.reorder_threshold),
                        below_reorder_threshold=inv.available_quantity <= inv.reorder_threshold,
                        updated_at=inv.updated_at)


def list_inventory(session: Session, *, status=None, search=None, page=1, page_size=25):
    q = select(Inventory).join(Product)
    if search:
        q = q.where(or_(Product.name.ilike(_like(search), escape="\\"), Product.sku.ilike(_like(search), escape="\\")))
    if status == "out_of_stock":
        q = q.where(Inventory.available_quantity <= 0)
    elif status == "low_stock":
        q = q.where(Inventory.available_quantity > 0, Inventory.available_quantity <= Inventory.reorder_threshold)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.options(joinedload(Inventory.product).joinedload(Product.category))
                           .order_by(Inventory.available_quantity.asc(), Product.name)
                           .limit(page_size).offset((page - 1) * page_size)).unique().all()
    return [inventory_out(r) for r in rows], total


def adjust_inventory(session: Session, user, product_id: int, *, set_available, delta, reorder_threshold, reason,
                     correlation_id=None) -> Inventory:
    """Administrator stock correction. Every change is audited with its reason."""
    if (set_available is None) == (delta is None) and reorder_threshold is None:
        raise HTTPException(422, "Provide set_available or delta (not both), or a reorder_threshold")
    if set_available is not None and delta is not None:
        raise HTTPException(422, "Provide either set_available or delta, not both")
    inv = session.scalar(select(Inventory).where(Inventory.product_id == product_id)
                         .options(joinedload(Inventory.product)))
    if inv is None:
        raise HTTPException(404, "Product not found")
    before = {"available_quantity": inv.available_quantity, "reorder_threshold": inv.reorder_threshold}
    new_available = inv.available_quantity
    if set_available is not None:
        new_available = set_available
    elif delta is not None:
        new_available = inv.available_quantity + delta
    if new_available < 0:
        raise HTTPException(422, "Stock cannot go below zero")
    inv.available_quantity = new_available
    if reorder_threshold is not None:
        inv.reorder_threshold = reorder_threshold
    record_audit(session, actor=user, action="inventory.adjusted", entity_type="inventory", entity_id=product_id,
                 before=before, after={"available_quantity": inv.available_quantity,
                                       "reorder_threshold": inv.reorder_threshold, "reason": reason},
                 correlation_id=correlation_id)
    session.flush()
    session.refresh(inv)
    return inv
