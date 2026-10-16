"""Administration: local demo users and roles, the audit trail, and integration status (no secrets)."""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from ..auth import User, require
from ..core import permissions as perm
from ..db.models import AppUser, AuditEvent
from ..dependencies import correlation, get_session
from ..services.audit import record_audit
from ..services.scamwatch_service import provider_status

router = APIRouter(tags=["admin"])


def user_out(u: AppUser) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at}


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["customer", "fraud_analyst", "security_analyst", "admin"] | None = None
    is_active: bool | None = None


@router.get("/admin/users")
def list_users(request: Request, user: User = Depends(require("users.manage")), session=Depends(get_session)):
    rows = session.scalars(select(AppUser).order_by(AppUser.email)).all()
    s = request.app.state.settings
    return {"items": [user_out(u) for u in rows], "local_auth_enabled": s.local_auth_enabled,
            "note": ("These are LOCAL demonstration accounts. Users who sign in through Supabase have their role set "
                     "in Supabase (app_metadata.role); see the README.")}


@router.patch("/admin/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, request: Request, user: User = Depends(require("users.manage"))):
    if body.role is None and body.is_active is None:
        raise HTTPException(422, "Nothing to change")
    with request.app.state.db.session() as session:
        target = session.get(AppUser, user_id)
        if target is None:
            raise HTTPException(404, "User not found")
        if target.id == user.id:
            raise HTTPException(409, "You cannot change your own role or status")     # prevents locking yourself out
        before = {"role": target.role, "is_active": target.is_active}
        new_role = body.role if body.role is not None else target.role
        new_active = body.is_active if body.is_active is not None else target.is_active
        if target.role == perm.ADMIN and (new_role != perm.ADMIN or not new_active):
            others = session.scalar(select(func.count()).select_from(AppUser).where(
                AppUser.role == perm.ADMIN, AppUser.is_active.is_(True), AppUser.id != target.id))
            if not others:
                raise HTTPException(409, "At least one active administrator must remain")
        target.role, target.is_active = new_role, new_active
        record_audit(session, actor=user, action="user.updated", entity_type="user", entity_id=target.id, before=before,
                     after={"role": target.role, "is_active": target.is_active}, correlation_id=correlation(request))
        out = user_out(target)
    request.app.state.events.record("medium", "privileged", "privileged.user_changed",
                                    f"User {target.email} changed by an administrator", actor_id=user.id,
                                    path=request.url.path, method="PATCH", correlation_id=correlation(request),
                                    details={"before": before, "after": {"role": new_role, "is_active": new_active}})
    return out


@router.get("/audit")
def list_audit(action: Annotated[str | None, Query(max_length=60, pattern=r"^[a-z_.]+$")] = None,
               entity_type: Annotated[str | None, Query(max_length=30, pattern=r"^[a-z_]+$")] = None,
               actor_id: Annotated[str | None, Query(max_length=64)] = None,
               date_from: str | None = None, date_to: str | None = None,
               page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25,
               user: User = Depends(require("audit.view")), session=Depends(get_session)):
    q = select(AuditEvent)
    if action:
        q = q.where(AuditEvent.action == action)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    try:
        d_from = date.fromisoformat(date_from) if date_from else None
        d_to = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(422, "dates must look like 2026-10-15")
    if d_from:
        q = q.where(AuditEvent.created_at >= datetime.combine(d_from, datetime.min.time(), timezone.utc))
    if d_to:
        q = q.where(AuditEvent.created_at < datetime.combine(d_to + timedelta(days=1), datetime.min.time(), timezone.utc))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                           .limit(page_size).offset((page - 1) * page_size)).all()
    items = [{"id": e.id, "created_at": e.created_at, "actor_id": e.actor_id, "actor_role": e.actor_role,
              "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id,
              "before": json.loads(e.before_json or "{}"), "after": json.loads(e.after_json or "{}"),
              "correlation_id": e.correlation_id} for e in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/settings/integrations")
def integrations(request: Request, user: User = Depends(require("settings.view"))):
    """What is configured and what is actually working. Secrets are reported only as yes/no."""
    app = request.app
    s = app.state.settings
    p, pca = app.state.predictor, app.state.pca
    return {
        "store": {"name": s.store_name, "currency": s.store_currency, "is_demo": s.store_is_demo,
                  "payment": "SIMULATED: no real payment provider is connected"},
        "retailer_connection": {"connected": False,
                                "note": "No real retailer system is connected. All store and event data is demonstration data."},
        "database": {"application_db": "connected" if app.state.db.ping() else "unavailable",
                     "application_db_engine": "sqlite" if app.state.db.is_sqlite else "postgresql",
                     "prediction_store": s.db_backend},
        "authentication": {"supabase_configured": bool(s.supabase_url or s.supabase_jwt_secret),
                           "supabase_live_tested": False, "local_demo_auth_enabled": s.local_auth_enabled,
                           "warning": ("Local demonstration sign-in is ON. Never enable it on a server others can reach."
                                       if s.local_auth_enabled else None)},
        "payment_model": ({"available": True, "version": p.metadata["version"], "is_synthetic": p.metadata["is_synthetic"],
                           "threshold": p.threshold, "trained_at": p.metadata["trained_at"]}
                          if p.available else {"available": False, "message": p.error}),
        "pca_model": ({"available": True, "version": pca.metadata["version"], "trained_at": pca.metadata["trained_at"]}
                      if pca.available else {"available": False, "message": pca.error}),
        "scamwatch_providers": provider_status(s),
        "rate_limits_per_minute": {"predict": s.predict_rate_limit_per_min, "checkout": s.checkout_rate_limit_per_min,
                                   "cart": s.cart_rate_limit_per_min, "scamwatch": s.scamwatch_rate_limit_per_min,
                                   "login": s.login_rate_limit_per_min},
        "alert_thresholds": app.state.events.thresholds(),
        "risk_bands": {"high": s.risk_high, "medium": s.risk_medium},
    }
