"""Catalogue administration: create and edit products and categories (administrators only).

* Every price change writes a `price_history` row and an audit event, in the same transaction as the change.
* New stock goes through the stock ledger, so opening stock + movements always equals the inventory row.
* A price entered here is the store's own price, so it is recorded as 'verified' from source type 'store'. Products are
  never deleted (orders keep snapshots); a product is withdrawn by setting `is_active` false.
* Images are references: a path in the frontend's /products folder or an https:// URL. Files are not uploaded to this
  server, because most hosts discard local files on every deploy.
"""
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ..auth import User, require
from ..db.models import Category, Inventory, PriceHistory, Product, effective_price_cents
from ..dependencies import correlation, get_session
from ..services.audit import record_audit
from ..services.stock_ledger import record_movement

router = APIRouter(tags=["catalogue-admin"])
MAX_PRICE_CENTS = 100_000_00        # K100,000: a typo guard, not a business rule
_SKU = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,39}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,58}$")


def _image_ok(v: str) -> str:
    v = v.strip()
    if v and not (re.match(r"^/[A-Za-z0-9._/-]{1,198}$", v) or re.match(r"^https://[^\s<>\"']{4,190}$", v)):
        raise ValueError("image must be a path like /products/x.jpg or an https:// address")
    return v


class _ProductFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    category_slug: str | None = Field(default=None, max_length=60)
    price_cents: int | None = Field(default=None, ge=0, le=MAX_PRICE_CENTS)
    offer_price_cents: int | None = Field(default=None, ge=0, le=MAX_PRICE_CENTS)
    offer_starts_on: date | None = None
    offer_ends_on: date | None = None
    unit: str | None = Field(default=None, max_length=30)
    brand: str | None = Field(default=None, max_length=80)
    pack_size: str | None = Field(default=None, max_length=40)
    image_ref: str | None = Field(default=None, max_length=200)
    image_alt: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    is_featured: bool | None = None

    @field_validator("image_ref")
    @classmethod
    def _img(cls, v):
        return _image_ok(v) if v is not None else v

    @model_validator(mode="after")
    def _offer_dates(self):
        if self.offer_starts_on and self.offer_ends_on and self.offer_starts_on > self.offer_ends_on:
            raise ValueError("offer_starts_on must not be after offer_ends_on")
        return self


class ProductCreate(_ProductFields):
    sku: str
    name: str = Field(min_length=2, max_length=160)
    category_slug: str = Field(max_length=60)
    price_cents: int = Field(ge=0, le=MAX_PRICE_CENTS)
    initial_quantity: int = Field(default=0, ge=0, le=1_000_000)
    reorder_threshold: int = Field(default=5, ge=0, le=1_000_000)

    @field_validator("sku")
    @classmethod
    def _sku_ok(cls, v: str) -> str:
        v = v.strip().upper()
        if not _SKU.match(v):
            raise ValueError("SKU must be 3-40 letters, digits or dashes")
        return v


class ProductUpdate(_ProductFields):
    clear_offer: bool = False


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    slug: str | None = Field(default=None, max_length=60)
    sort_order: int = Field(default=100, ge=0, le=10000)


def _out(p: Product) -> dict:
    inv = p.inventory
    return {"id": p.id, "sku": p.sku, "name": p.name, "description": p.description, "category_slug": p.category.slug,
            "category_name": p.category.name, "price_cents": p.price_cents, "offer_price_cents": p.offer_price_cents,
            "offer_starts_on": p.offer_starts_on, "offer_ends_on": p.offer_ends_on,
            "effective_price_cents": effective_price_cents(p), "currency": p.currency, "unit": p.unit, "brand": p.brand,
            "pack_size": p.pack_size, "image_ref": p.image_ref, "image_alt": p.image_alt, "image_status": p.image_status,
            "price_status": p.price_status, "is_active": p.is_active, "is_featured": p.is_featured, "is_demo": p.is_demo,
            "available_quantity": inv.available_quantity if inv else 0, "reserved_quantity": inv.reserved_quantity if inv else 0,
            "reorder_threshold": inv.reorder_threshold if inv else 0, "updated_at": p.updated_at}


def _category(session, slug: str) -> Category:
    c = session.scalar(select(Category).where(Category.slug == slug))
    if c is None:
        raise HTTPException(422, f"Unknown category '{slug}'. Create it first.")
    return c


def _check_offer(price: int, offer: int | None):
    if offer is not None and offer >= price:
        raise HTTPException(422, "The offer price must be lower than the normal price.")


def _price_row(session, p: Product, actor_id: str):
    session.add(PriceHistory(product_id=p.id, price_cents=p.price_cents, offer_price_cents=p.offer_price_cents,
                             currency=p.currency, price_status=p.price_status, source_url="", recorded_by=actor_id))


@router.get("/admin/products")
def list_products(search: str | None = Query(default=None, max_length=60), include_inactive: bool = True,
                  page: int = Query(1, ge=1, le=10000), page_size: int = Query(25, ge=1, le=100),
                  user: User = Depends(require("catalogue.manage")), session=Depends(get_session)):
    q = select(Product)
    if not include_inactive:
        q = q.where(Product.is_active.is_(True))
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where(or_(Product.name.ilike(like, escape="\\"), Product.sku.ilike(like, escape="\\"),
                        Product.brand.ilike(like, escape="\\")))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.options(joinedload(Product.category), joinedload(Product.inventory)).order_by(Product.name, Product.id)
                           .limit(page_size).offset((page - 1) * page_size)).unique().all()
    return {"items": [_out(p) for p in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/admin/products", status_code=201)
def create_product(body: ProductCreate, request: Request, user: User = Depends(require("catalogue.manage"))):
    s = request.app.state.settings
    with request.app.state.db.session() as session:
        cat = _category(session, body.category_slug)
        _check_offer(body.price_cents, body.offer_price_cents)
        p = Product(sku=body.sku, name=body.name, description=body.description or "", category_id=cat.id,
                    price_cents=body.price_cents, offer_price_cents=body.offer_price_cents,
                    offer_starts_on=body.offer_starts_on, offer_ends_on=body.offer_ends_on, currency=s.store_currency,
                    unit=body.unit or "each", brand=body.brand or "", pack_size=body.pack_size or "",
                    image_ref=body.image_ref or "", image_alt=body.image_alt or body.name,
                    image_status="licensed" if body.image_ref else "placeholder", price_status="verified",
                    price_source_type="store", price_source_name="Store price list", price_checked_on=date.today(),
                    is_active=True if body.is_active is None else body.is_active, is_featured=bool(body.is_featured), is_demo=False)
        session.add(p)
        try:
            session.flush()
        except IntegrityError:
            raise HTTPException(409, f"A product with SKU {body.sku} already exists.")
        session.add(Inventory(product_id=p.id, available_quantity=body.initial_quantity, reserved_quantity=0,
                              reorder_threshold=body.reorder_threshold))
        record_movement(session, product_id=p.id, delta_available=body.initial_quantity, reason="initial_stock",
                        actor_id=user.id, note="new product")
        _price_row(session, p, user.id)
        record_audit(session, actor=user, action="product.created", entity_type="product", entity_id=p.id,
                     after={"sku": p.sku, "name": p.name, "price_cents": p.price_cents, "stock": body.initial_quantity},
                     correlation_id=correlation(request))
        session.flush()
        session.refresh(p)
        return _out(p)


@router.patch("/admin/products/{product_id}")
def update_product(product_id: int, body: ProductUpdate, request: Request, user: User = Depends(require("catalogue.manage"))):
    with request.app.state.db.session() as session:
        p = session.scalar(select(Product).where(Product.id == product_id)
                           .options(joinedload(Product.category), joinedload(Product.inventory)))
        if p is None:
            raise HTTPException(404, "Product not found")
        before = {"price_cents": p.price_cents, "offer_price_cents": p.offer_price_cents, "is_active": p.is_active,
                  "name": p.name, "category": p.category.slug}
        data = body.model_dump(exclude_unset=True, exclude={"clear_offer", "category_slug"})
        if body.category_slug:
            p.category_id = _category(session, body.category_slug).id
        for k, v in data.items():
            if v is not None or k in ("offer_price_cents", "offer_starts_on", "offer_ends_on"):
                setattr(p, k, v)
        if body.clear_offer:
            p.offer_price_cents = p.offer_starts_on = p.offer_ends_on = None
        _check_offer(p.price_cents, p.offer_price_cents)
        if "image_ref" in data and data["image_ref"]:
            p.image_status = "licensed"
        price_changed = (p.price_cents, p.offer_price_cents) != (before["price_cents"], before["offer_price_cents"])
        if price_changed:
            p.price_status, p.price_source_type, p.price_checked_on, p.is_demo = "verified", "store", date.today(), False
            session.flush()
            _price_row(session, p, user.id)
        session.flush()
        session.refresh(p)
        record_audit(session, actor=user, action="product.price_changed" if price_changed else "product.updated",
                     entity_type="product", entity_id=p.id, before=before,
                     after={"price_cents": p.price_cents, "offer_price_cents": p.offer_price_cents, "is_active": p.is_active,
                            "name": p.name, "category": p.category.slug}, correlation_id=correlation(request))
        return _out(p)


@router.get("/admin/products/{product_id}/price-history")
def price_history(product_id: int, user: User = Depends(require("catalogue.manage")), session=Depends(get_session)):
    rows = session.scalars(select(PriceHistory).where(PriceHistory.product_id == product_id)
                           .order_by(PriceHistory.recorded_at.desc(), PriceHistory.id.desc()).limit(100)).all()
    return {"items": [{"price_cents": r.price_cents, "offer_price_cents": r.offer_price_cents, "currency": r.currency,
                       "price_status": r.price_status, "recorded_by": r.recorded_by, "recorded_at": r.recorded_at} for r in rows]}


@router.post("/admin/categories", status_code=201)
def create_category(body: CategoryCreate, request: Request, user: User = Depends(require("catalogue.manage"))):
    slug = (body.slug or re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-"))[:60]
    if not _SLUG.match(slug):
        raise HTTPException(422, "The category name cannot be turned into a valid web address; give a slug.")
    with request.app.state.db.session() as session:
        c = Category(slug=slug, name=body.name, sort_order=body.sort_order)
        session.add(c)
        try:
            session.flush()
        except IntegrityError:
            raise HTTPException(409, "A category with that slug already exists.")
        record_audit(session, actor=user, action="category.created", entity_type="category", entity_id=c.id,
                     after={"slug": slug, "name": body.name}, correlation_id=correlation(request))
        return {"id": c.id, "slug": c.slug, "name": c.name}
