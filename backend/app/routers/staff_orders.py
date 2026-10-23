"""Staff view of store orders: orders joined to their payments, risk assessments and cases.

Contact details are masked for roles that do not manage orders (analysts need to judge risk, not to read customers'
phone numbers). Administrators see them in full, and each such view is written to the audit trail."""
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from ..auth import User, require
from pydantic import BaseModel, ConfigDict, Field

from ..db.models import Case, FraudAssessment, MlPrediction, Order, OrderOutcome, OrderStatusHistory
from ..dependencies import get_session
from ..services import ml_scoring, order_service, store_risk
from ..services.audit import record_audit

router = APIRouter(tags=["staff-orders"])


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"+{digits[:5]}****{digits[-3:]}" if len(digits) >= 9 else "****"


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def _latest_assessment_ids():
    return select(func.max(FraudAssessment.id)).group_by(FraudAssessment.order_id)


def _risk(row: FraudAssessment | None):
    return None if row is None else {"score": row.score, "decision": row.decision, "engine": f"{row.engine}_{row.version}"}


def _case(session, order_id: str):
    c = session.scalar(select(Case).where(Case.source_type == "order_anomaly", Case.source_record_id == order_id))
    return None if c is None else {"id": c.id, "case_reference": c.case_reference, "status": c.status, "severity": c.severity}


@router.get("/staff/orders")
def list_staff_orders(page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
                      status: Annotated[str | None, Query(max_length=24)] = None,
                      payment_status: Annotated[str | None, Query(max_length=24)] = None,
                      decision: Annotated[str | None, Query(pattern="^(allow|review|high)$")] = None,
                      search: Annotated[str | None, Query(max_length=40)] = None,
                      user: User = Depends(require("orders.view_all")), session=Depends(get_session)):
    q = select(Order)
    if status:
        q = q.where(Order.status == status)
    if payment_status:
        q = q.where(Order.payment_status == payment_status)
    if decision:
        q = q.where(Order.id.in_(select(FraudAssessment.order_id).where(FraudAssessment.id.in_(_latest_assessment_ids()),
                                                                          FraudAssessment.decision == decision)))
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where(or_(Order.reference.ilike(like, escape="\\"), Order.contact_name.ilike(like, escape="\\")))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.execute(q.options(joinedload(Order.items)).order_by(Order.created_at.desc(), Order.id)
                           .limit(page_size).offset((page - 1) * page_size)).unique().scalars().all()
    items = []
    for o in rows:
        items.append({"id": o.id, "reference": o.reference, "created_at": o.created_at, "status": o.status,
                      "payment_status": o.payment_status, "payment_method": o.payment_method, "payment_mode": o.payment_mode,
                      "total_cents": o.total_cents, "currency": o.currency, "fulfilment": o.fulfilment,
                      "contact_name": o.contact_name, "item_count": sum(i.quantity for i in o.items),
                      "risk": _risk(store_risk.latest(session, o.id)), "case": _case(session, o.id)})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/staff/orders/{order_id}")
def staff_order_detail(order_id: str, request: Request, user: User = Depends(require("orders.view_all")),
                       session=Depends(get_session)):
    try:
        oid = str(uuid.UUID(order_id))
    except ValueError:
        raise HTTPException(404, "Order not found")
    order = order_service.get_order(session, oid)
    if order is None:
        raise HTTPException(404, "Order not found")
    full = user.has("orders.manage")
    view = order_service.order_view(session, order).model_dump(mode="json")
    if not full:
        view["contact_email"], view["contact_phone"] = mask_email(order.contact_email), mask_phone(order.contact_phone)
        view["address_line"] = "(hidden)" if order.address_line else ""
        view["delivery_instructions"] = ""
    else:
        record_audit(session, actor=user, action="order.contact_viewed", entity_type="order", entity_id=order.id,
                     after={"reference": order.reference})
    history = session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == oid)
                              .order_by(OrderStatusHistory.id)).all()
    assessments = session.scalars(select(FraudAssessment).where(FraudAssessment.order_id == oid)
                                  .order_by(FraudAssessment.created_at.desc(), FraudAssessment.id.desc())).all()
    ml_rows = session.scalars(select(MlPrediction).where(MlPrediction.order_id == oid).order_by(MlPrediction.id.desc())).all()
    outcomes = session.scalars(select(OrderOutcome).where(OrderOutcome.order_id == oid).order_by(OrderOutcome.id.desc())).all()
    return {"order": view, "contact_masked": not full,
            "assessments": [store_risk.out(a) for a in assessments], "case": _case(session, oid),
            "ml_predictions": [ml_scoring.public_view(r) for r in ml_rows],
            "outcomes": [_outcome_out(o) for o in outcomes],
            "history": [{"from": h.from_status, "to": h.to_status, "reason": h.reason, "actor_id": h.actor_id,
                         "at": h.created_at} for h in history]}


@router.get("/staff/risk-summary")
def risk_summary(user: User = Depends(require("orders.view_all")), session=Depends(get_session)):
    """Counts of orders by their current risk decision, for the dashboard."""
    rows = session.execute(select(FraudAssessment.decision, func.count()).where(FraudAssessment.id.in_(_latest_assessment_ids()))
                           .group_by(FraudAssessment.decision)).all()
    counts = {"allow": 0, "review": 0, "high": 0, **{d: n for d, n in rows}}
    return {"engine": "store_risk_v1", "counts": counts, "note": store_risk.NOTE}


class OutcomeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str = Field(pattern="^(confirmed_fraud|false_positive|legitimate|undetermined)$")
    verified: bool = False
    note: str = Field("", max_length=500)


def _outcome_out(o: OrderOutcome) -> dict:
    return {"id": o.id, "outcome": o.outcome, "verified": o.verified, "note": o.note, "reviewer_id": o.reviewer_id,
            "created_at": o.created_at.isoformat() if o.created_at else None}


@router.post("/staff/orders/{order_id}/outcome", status_code=201)
def record_outcome(order_id: str, body: OutcomeIn, user: User = Depends(require("fraud.review")), session=Depends(get_session)):
    """Append a reviewer's conclusion. History is never overwritten. Only verified outcomes may later be used as training
    labels, and nothing retrains automatically."""
    try:
        oid = str(uuid.UUID(order_id))
    except ValueError:
        raise HTTPException(404, "Order not found")
    if order_service.get_order(session, oid) is None:
        raise HTTPException(404, "Order not found")
    row = OrderOutcome(order_id=oid, outcome=body.outcome, verified=body.verified, note=body.note.strip(), reviewer_id=user.id)
    session.add(row)
    session.flush()
    record_audit(session, actor=user, action="order.outcome_recorded", entity_type="order", entity_id=oid,
                 after={"outcome": body.outcome, "verified": body.verified})
    return _outcome_out(row)


@router.get("/staff/orders/{order_id}/outcome")
def list_outcomes(order_id: str, user: User = Depends(require("fraud.view")), session=Depends(get_session)):
    try:
        oid = str(uuid.UUID(order_id))
    except ValueError:
        raise HTTPException(404, "Order not found")
    rows = session.scalars(select(OrderOutcome).where(OrderOutcome.order_id == oid).order_by(OrderOutcome.id.desc())).all()
    return {"outcomes": [_outcome_out(o) for o in rows]}


@router.get("/staff/ml-summary")
def ml_summary(user: User = Depends(require("fraud.view")), session=Depends(get_session)):
    """Live counts for the dashboard: how many store events the models could and could not score, and recorded outcomes."""
    status_rows = session.execute(select(MlPrediction.status, func.count()).group_by(MlPrediction.status)).all()
    outcome_rows = session.execute(select(OrderOutcome.outcome, func.count()).where(OrderOutcome.verified.is_(True))
                                   .group_by(OrderOutcome.outcome)).all()
    return {"prediction_status_counts": {k: n for k, n in status_rows},
            "verified_outcome_counts": {k: n for k, n in outcome_rows},
            "note": "Verified outcomes are stored for future, reviewed retraining. Nothing retrains automatically."}


AUDIT_SAMPLE_RATE = 10        # one in N unflagged orders is put forward each ISO week, chosen by a hash (not by anyone's judgement)


def _in_audit_sample(order_id: str, when) -> bool:
    import hashlib
    year, week, _ = when.isocalendar()
    return int(hashlib.sha256(f"{order_id}:{year}-{week}".encode()).hexdigest(), 16) % AUDIT_SAMPLE_RATE == 0


@router.get("/staff/label-queue")
def label_queue(limit: Annotated[int, Query(ge=1, le=100)] = 30, user: User = Depends(require("fraud.view")), session=Depends(get_session)):
    """Orders still waiting for a verified outcome: rule-flagged orders first, then a deterministic audit sample of UNFLAGGED orders.
    Reviewing the sample keeps the labels from covering only what the rules already catch (see docs/LABEL_COLLECTION.md).
    Bounded queries: never reads the whole assessments table."""
    from datetime import timedelta

    from ..db.models import utcnow
    verified = select(OrderOutcome.order_id).where(OrderOutcome.verified.is_(True), OrderOutcome.outcome != "undetermined")
    newest = select(func.max(FraudAssessment.id)).group_by(FraudAssessment.order_id)
    base = (select(FraudAssessment, Order).join(Order, Order.id == FraudAssessment.order_id)
            .where(FraudAssessment.id.in_(newest), Order.id.not_in(verified)))

    def item(a, o, why):
        return {"order_id": o.id, "reference": o.reference, "created_at": o.created_at.isoformat(), "total_cents": o.total_cents,
                "currency": o.currency, "rules_score": a.score, "rules_decision": a.decision, "why": why}

    flagged_q = base.where(FraudAssessment.decision != "allow").order_by(FraudAssessment.score.desc(), Order.created_at.desc())
    flagged = [item(a, o, "flagged by rules") for a, o in session.execute(flagged_q.limit(500))]
    flagged_total = session.scalar(select(func.count()).select_from(flagged_q.subquery()))
    recent = base.where(FraudAssessment.decision == "allow", Order.created_at >= utcnow() - timedelta(days=14))         .order_by(Order.created_at.desc()).limit(2000)
    sample = [item(a, o, "audit sample (unflagged)") for a, o in session.execute(recent) if _in_audit_sample(o.id, o.created_at)]
    return {"items": (flagged + sample)[:limit], "flagged_waiting": flagged_total, "audit_sample_waiting": len(sample),
            "audit_sample_rate": f"1 in {AUDIT_SAMPLE_RATE} unflagged orders per week"}
