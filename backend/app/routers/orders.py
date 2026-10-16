"""Checkout and orders. Customers see only their own orders; staff with the permission see all."""
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..auth import User, require
from ..db.models import Order
from ..dependencies import correlation, get_session, limited
from ..schemas.store import OrderCreate, OrderOut, OrderPage, OrderStatusUpdate
from ..services import order_risk, order_service

log = logging.getLogger("fraudguard")
router = APIRouter(tags=["orders"])


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(404, "Order not found")


def _visible(order: Order | None, user: User) -> Order:
    # The same 404 for "does not exist" and "belongs to someone else": ids reveal nothing.
    if order is None or (order.user_id != user.id and not user.has("orders.view_all")):
        raise HTTPException(404, "Order not found")
    return order


@router.post("/orders", response_model=OrderOut, status_code=201,
             dependencies=[Depends(limited("checkout", "checkout_rate_limit_per_min"))])
def place_order(payload: OrderCreate, request: Request, user: User = Depends(require("store.shop"))):
    app = request.app
    cid = correlation(request)
    try:
        with app.state.db.session() as session:        # one transaction: commit only if every line was reserved
            order = order_service.create_order(session, user, payload, app.state.settings, cid)
            out = order_service.order_out(order)
    except order_service.CheckoutRejected as exc:      # the transaction has been rolled back by now
        app.state.events.record("low", "order", "order.checkout_rejected", "Checkout rejected: " + "; ".join(
            p["message"] for p in exc.problems)[:300], actor_id=user.id, path=request.url.path, method="POST",
            status_code=409, correlation_id=cid, details={"problems": exc.problems})
        raise HTTPException(409, detail={"message": "Some items in your cart can no longer be ordered as requested.",
                                         "problems": exc.problems})
    try:
        order_risk.evaluate(app.state.db, app.state.events, app.state.settings, out.id, cid)
    except Exception:
        log.exception("order risk evaluation failed")   # never fail a placed order because monitoring failed
    return out


@router.get("/orders", response_model=OrderPage)
def list_orders(page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 10,
                all: bool = False, user: User = Depends(require("store.shop")), session=Depends(get_session)):
    q = select(Order)
    if all:
        if not user.has("orders.view_all"):
            raise HTTPException(403, "You do not have permission to do this")
    else:
        q = q.where(Order.user_id == user.id)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.execute(q.options(joinedload(Order.items)).order_by(Order.created_at.desc(), Order.id)
                           .limit(page_size).offset((page - 1) * page_size)).unique().scalars().all()
    return OrderPage(items=[order_service.order_out(o) for o in rows], total=total, page=page, page_size=page_size)


@router.get("/orders/{order_id}", response_model=OrderOut)
def read_order(order_id: str, user: User = Depends(require("store.shop")), session=Depends(get_session)):
    return order_service.order_out(_visible(order_service.get_order(session, _uuid(order_id)), user))


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: str, request: Request, user: User = Depends(require("store.shop"))):
    """The owner may cancel while the order is still 'confirmed'; an administrator may cancel any open order."""
    with request.app.state.db.session() as session:
        order = _visible(order_service.get_order(session, _uuid(order_id)), user)
        if not user.has("orders.manage"):
            if order.user_id != user.id:
                raise HTTPException(404, "Order not found")
            if order.status != "confirmed":
                raise HTTPException(409, "This order is already being prepared and can no longer be cancelled here.")
        order = order_service.change_status(session, user, order, "cancelled", correlation(request))
        return order_service.order_out(order)


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_status(order_id: str, body: OrderStatusUpdate, request: Request,
                  user: User = Depends(require("orders.manage"))):
    with request.app.state.db.session() as session:
        order = order_service.get_order(session, _uuid(order_id))
        if order is None:
            raise HTTPException(404, "Order not found")
        order = order_service.change_status(session, user, order, body.status, correlation(request))
        return order_service.order_out(order)
