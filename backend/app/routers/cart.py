"""Shopping cart. Every route works on the SIGNED-IN user's own cart; the user id comes from the token."""
from fastapi import APIRouter, Depends, Request, Response

from ..auth import User, require
from ..dependencies import get_session, limited
from ..schemas.store import CartAdd, CartOut, CartUpdate
from ..services import cart_service, order_service

router = APIRouter(tags=["cart"])
guard = Depends(limited("cart", "cart_rate_limit_per_min"))


@router.get("/cart", response_model=CartOut)
def read_cart(request: Request, user: User = Depends(require("store.shop")), session=Depends(get_session)):
    return cart_service.cart_view(session, user.id, request.app.state.settings)


@router.post("/cart/items", response_model=CartOut, status_code=201, dependencies=[guard])
def add_to_cart(body: CartAdd, request: Request, user: User = Depends(require("store.shop")),
                session=Depends(get_session)):
    s = request.app.state.settings
    order_service.expire_unpaid_orders(session)          # units from abandoned orders are back on sale before we check stock
    cart_service.add_item(session, user.id, body.product_id, body.quantity, s)
    return cart_service.cart_view(session, user.id, s)


@router.patch("/cart/items/{item_id}", response_model=CartOut, dependencies=[guard])
def update_cart_item(item_id: int, body: CartUpdate, request: Request, user: User = Depends(require("store.shop")),
                     session=Depends(get_session)):
    s = request.app.state.settings
    order_service.expire_unpaid_orders(session)
    cart_service.update_item(session, user.id, item_id, body.quantity, s)
    return cart_service.cart_view(session, user.id, s)


@router.delete("/cart/items/{item_id}", response_model=CartOut, dependencies=[guard])
def delete_cart_item(item_id: int, request: Request, user: User = Depends(require("store.shop")),
                     session=Depends(get_session)):
    cart_service.remove_item(session, user.id, item_id)
    return cart_service.cart_view(session, user.id, request.app.state.settings)
