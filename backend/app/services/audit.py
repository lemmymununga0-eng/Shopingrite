"""Append-only audit trail. Written in the SAME transaction as the change it describes."""
import json

from sqlalchemy.orm import Session

from ..core.security import redact
from ..db.models import AuditEvent


def record_audit(session: Session, *, actor, action: str, entity_type: str, entity_id, before=None, after=None,
                 correlation_id: str | None = None) -> AuditEvent:
    """`actor` is an auth.User (or None for system actions)."""
    ev = AuditEvent(
        actor_id=getattr(actor, "id", None), actor_role=getattr(actor, "role", None) if actor else "system",
        action=action, entity_type=entity_type, entity_id=str(entity_id),
        before_json=json.dumps(redact(before or {}), default=str), after_json=json.dumps(redact(after or {}), default=str),
        correlation_id=correlation_id)
    session.add(ev)
    return ev
