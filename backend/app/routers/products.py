"""Public catalogue endpoints (browsing needs no sign-in) and store identity."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from ..dependencies import get_session
from ..schemas.store import CategoryOut, ProductOut, ProductPage
from ..services import inventory_service as inv

router = APIRouter(tags=["store"])


@router.get("/store-info")
def store_info(request: Request):
    s = request.app.state.settings
    return {"name": s.store_name, "currency": s.store_currency, "is_demo": s.store_is_demo,
            "delivery_cities": s.city_list, "delivery_fee_cents": s.delivery_fee_cents,
            "free_delivery_over_cents": s.free_delivery_over_cents, "max_quantity_per_line": s.max_quantity_per_line,
            "local_auth_enabled": s.local_auth_enabled, "console_admin_only": s.console_admin_only,
            "legal_name": s.store_legal_name or s.store_name, "contact_email": s.store_contact_email,
            "contact_phone": s.store_contact_phone, "contact_address": s.store_contact_address,
            "disclaimer": ("Independent demonstration store with sample products and sample stock. It is not "
                           "affiliated with, endorsed by, or connected to any real retailer. Payments are simulated; "
                           "no money is taken.") if s.store_is_demo else ""}


@router.get("/categories", response_model=list[CategoryOut])
def categories(session=Depends(get_session)):
    return inv.list_categories(session)


@router.get("/products", response_model=ProductPage)
def products(search: Annotated[str | None, Query(max_length=60)] = None,
             category: Annotated[str | None, Query(max_length=60, pattern=r"^[a-z0-9-]+$")] = None,
             min_price: Annotated[float | None, Query(ge=0, le=1_000_000)] = None,
             max_price: Annotated[float | None, Query(ge=0, le=1_000_000)] = None,
             sort: Literal["name", "price_asc", "price_desc", "newest", "popular"] = "name",
             in_stock_only: bool = False, on_offer: bool = False, featured: bool = False,
             page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=60)] = 12,
             session=Depends(get_session)):
    items, total = inv.list_products(
        session, search=search, category=category,
        min_price_cents=None if min_price is None else round(min_price * 100),
        max_price_cents=None if max_price is None else round(max_price * 100),
        sort=sort, in_stock_only=in_stock_only, on_offer=on_offer, featured=featured, page=page, page_size=page_size)
    return ProductPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/products/{product_id}", response_model=ProductOut)
def product(product_id: int, session=Depends(get_session)):
    return inv.product_out(inv.get_product(session, product_id))
