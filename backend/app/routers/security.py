"""Security Monitor: the application's own security events. Not a view of any retailer network."""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ..auth import User, require
from ..db.models import AlertThreshold, SecurityEvent, utcnow
from ..dependencies import correlation, get_session
from ..services.audit import record_audit
from ..services.security_events import CATEGORIES, DEFAULT_THRESHOLDS, SEVERITIES

router = APIRouter(prefix="/security", tags=["security"])


def event_out(e: SecurityEvent, with_details: bool = False) -> dict:
    out = {"id": e.id, "created_at": e.created_at, "severity": e.severity, "category": e.category,
           "event_type": e.event_type, "message": e.message, "actor_id": e.actor_id, "client_tag": e.client_tag,
           "path": e.path, "method": e.method, "status_code": e.status_code, "correlation_id": e.correlation_id}
    if with_details:
        out["details"] = json.loads(e.details_json or "{}")
    return out


def _day(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{name} must be a date like 2026-10-15")


@router.get("/events")
def list_events(severity: Annotated[str | None, Query(max_length=10)] = None,
                category: Annotated[str | None, Query(max_length=30)] = None,
                search: Annotated[str | None, Query(max_length=80)] = None,
                correlation_id: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Za-z0-9._-]+$")] = None,
                date_from: str | None = None, date_to: str | None = None,
                page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25,
                user: User = Depends(require("security.view")), session=Depends(get_session)):
    if severity and severity not in SEVERITIES:
        raise HTTPException(422, "invalid severity")
    if category and category not in CATEGORIES:
        raise HTTPException(422, "invalid category")
    q = select(SecurityEvent)
    if severity:
        q = q.where(SecurityEvent.severity == severity)
    if category:
        q = q.where(SecurityEvent.category == category)
    if correlation_id:
        q = q.where(SecurityEvent.correlation_id == correlation_id)
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where(SecurityEvent.message.ilike(like, escape="\\") | SecurityEvent.event_type.ilike(like, escape="\\"))
    d_from, d_to = _day(date_from, "date_from"), _day(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(422, "date_from must not be after date_to")
    if d_from:
        q = q.where(SecurityEvent.created_at >= datetime.combine(d_from, datetime.min.time(), timezone.utc))
    if d_to:
        q = q.where(SecurityEvent.created_at < datetime.combine(d_to + timedelta(days=1), datetime.min.time(), timezone.utc))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
                           .limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [event_out(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/events/{event_id}")
def read_event(event_id: int, user: User = Depends(require("security.view")), session=Depends(get_session)):
    e = session.get(SecurityEvent, event_id)
    if e is None:
        raise HTTPException(404, "Event not found")
    return event_out(e, with_details=True)


@router.get("/summary")
def summary(days: Annotated[int, Query(ge=1, le=90)] = 7, user: User = Depends(require("security.view")),
            session=Depends(get_session)):
    since = utcnow() - timedelta(days=days)
    base = select(SecurityEvent).where(SecurityEvent.created_at >= since).subquery()
    by_sev = dict(session.execute(select(base.c.severity, func.count()).group_by(base.c.severity)).all())
    by_cat = dict(session.execute(select(base.c.category, func.count()).group_by(base.c.category)).all())
    recent_high = session.scalars(select(SecurityEvent).where(SecurityEvent.severity.in_(("high", "critical")))
                                  .order_by(SecurityEvent.created_at.desc()).limit(5)).all()
    return {"period_days": days, "total": sum(by_sev.values()), "by_severity": by_sev, "by_category": by_cat,
            "recent_high": [event_out(e) for e in recent_high],
            "scope_note": "Events recorded by this application only. This is not network or infrastructure monitoring."}


class ThresholdUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Annotated[int, Field(ge=1, le=100_000)]]


@router.get("/thresholds")
def thresholds(request: Request, user: User = Depends(require("security.view"))):
    return {"thresholds": request.app.state.events.thresholds(), "defaults": DEFAULT_THRESHOLDS,
            "window_minutes": 10}


@router.put("/thresholds")
def set_thresholds(body: ThresholdUpdate, request: Request, user: User = Depends(require("settings.edit"))):
    unknown = sorted(set(body.values) - set(DEFAULT_THRESHOLDS))
    if unknown:
        raise HTTPException(422, f"Unknown threshold(s): {', '.join(unknown)}")
    with request.app.state.db.session() as session:
        before = {}
        for key, value in body.values.items():
            row = session.get(AlertThreshold, key)
            before[key] = row.value if row else DEFAULT_THRESHOLDS[key]
            if row:
                row.value, row.updated_by = value, user.id
            else:
                session.add(AlertThreshold(key=key, value=value, updated_by=user.id))
        record_audit(session, actor=user, action="settings.thresholds_changed", entity_type="alert_thresholds",
                     entity_id="all", before=before, after=body.values, correlation_id=correlation(request))
    request.app.state.events.record("medium", "privileged", "privileged.thresholds_changed",
                                    "Security alert thresholds were changed", actor_id=user.id,
                                    path=request.url.path, method="PUT", correlation_id=correlation(request))
    return {"thresholds": request.app.state.events.thresholds()}
