"""Append-only stock ledger. Every change to `inventory` writes a row here in the same transaction, so
opening stock plus all movements always equals the current quantities (tested)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Inventory, StockMovement

REASONS = ("initial_stock", "order_reserved", "order_cancelled", "order_expired", "order_completed", "admin_adjustment")


def record_movement(session: Session, *, product_id: int, delta_available: int, delta_reserved: int = 0, reason: str,
                    order_id: str | None = None, actor_id: str | None = None, note: str = "") -> StockMovement:
    assert reason in REASONS, reason
    m = StockMovement(product_id=product_id, delta_available=delta_available, delta_reserved=delta_reserved,
                      reason=reason, order_id=order_id, actor_id=actor_id, note=note[:200])
    session.add(m)
    return m


def ledger_totals(session: Session, product_id: int) -> tuple[int, int]:
    """(available, reserved) implied by the ledger."""
    row = session.execute(select(func.coalesce(func.sum(StockMovement.delta_available), 0),
                                 func.coalesce(func.sum(StockMovement.delta_reserved), 0))
                          .where(StockMovement.product_id == product_id)).one()
    return int(row[0]), int(row[1])


def mismatches(session: Session) -> list[dict]:
    """Products whose inventory row disagrees with the ledger. Empty list = consistent."""
    bad = []
    for inv in session.scalars(select(Inventory)):
        a, r = ledger_totals(session, inv.product_id)
        if (a, r) != (inv.available_quantity, inv.reserved_quantity):
            bad.append({"product_id": inv.product_id, "inventory": (inv.available_quantity, inv.reserved_quantity),
                        "ledger": (a, r)})
    return bad
