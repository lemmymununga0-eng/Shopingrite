"""Staff inventory view and administrator stock corrections."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from ..auth import User, require
from ..dependencies import correlation, get_session
from ..schemas.store import InventoryAdjust, InventoryOut, InventoryPage
from ..services import inventory_service as inv

router = APIRouter(tags=["inventory"])


@router.get("/inventory", response_model=InventoryPage)
def list_inventory(status: Literal["low_stock", "out_of_stock"] | None = None,
                   search: Annotated[str | None, Query(max_length=60)] = None,
                   page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25,
                   user: User = Depends(require("inventory.view")), session=Depends(get_session)):
    items, total = inv.list_inventory(session, status=status, search=search, page=page, page_size=page_size)
    return InventoryPage(items=items, total=total, page=page, page_size=page_size)


@router.patch("/inventory/{product_id}", response_model=InventoryOut)
def adjust(product_id: int, body: InventoryAdjust, request: Request,
           user: User = Depends(require("inventory.adjust"))):
    with request.app.state.db.session() as session:
        row = inv.adjust_inventory(session, user, product_id, set_available=body.set_available, delta=body.delta,
                                   reorder_threshold=body.reorder_threshold, reason=body.reason,
                                   correlation_id=correlation(request))
        out = inv.inventory_out(row)
    request.app.state.events.record("low", "inventory", "inventory.adjusted",
                                    f"Stock for product {product_id} adjusted by an administrator",
                                    actor_id=user.id, path=request.url.path, method="PATCH",
                                    correlation_id=correlation(request), details={"product_id": product_id})
    return out
