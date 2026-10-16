"""Unified Investigation Centre: one case list fed by every kind of signal.

A model score or report is a SIGNAL that needs human review. It is never recorded as proof of wrongdoing.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import case as sql_case
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core import permissions as perm
from ..db.models import Case, CaseNote, utcnow
from .audit import record_audit

SOURCE_TYPES = ("fraud_prediction", "scamwatch_report", "security_alert", "order_anomaly", "manual")
STATUSES = ("new", "investigating", "confirmed", "false_positive", "resolved")
CLOSED = ("false_positive", "resolved")
SEVERITIES = ("low", "medium", "high", "critical")
SIGNAL_NOTE = "A model score or report is a signal for review, not proof of wrongdoing."
UNSET = "__unset__"


def _placeholder_reference() -> str:
    return "tmp-" + uuid.uuid4().hex[:16]


def ensure_case(session: Session, *, source_type: str, source_record_id: str, severity: str, summary: str,
                evidence_reference: str = "", created_by: str | None = None,
                correlation_id: str | None = None) -> tuple[Case, bool]:
    """Idempotent: one case per (source_type, source_record_id). Returns (case, created)."""
    def find():
        return session.scalar(select(Case).where(Case.source_type == source_type,
                                                 Case.source_record_id == str(source_record_id)))
    existing = find()
    if existing:
        return existing, False
    case = Case(case_reference=_placeholder_reference(), source_type=source_type, source_record_id=str(source_record_id),
                severity=severity, summary=summary[:500], evidence_reference=evidence_reference[:300],
                created_by=created_by)
    try:
        with session.begin_nested():
            session.add(case)
            session.flush()
    except IntegrityError:               # created concurrently by someone else
        again = find()
        if again:
            return again, False
        raise
    case.case_reference = f"CASE-{case.id:06d}"
    record_audit(session, actor=None, action="case.created", entity_type="case", entity_id=case.id,
                 after={"reference": case.case_reference, "source_type": source_type,
                        "source_record_id": source_record_id, "severity": severity}, correlation_id=correlation_id)
    return case, True


def serialize(case: Case, with_notes: bool = False) -> dict:
    out = {c: getattr(case, c) for c in ("id", "case_reference", "source_type", "source_record_id", "severity", "status",
                                         "summary", "evidence_reference", "assigned_to", "created_by", "created_at",
                                         "updated_at", "resolved_at")}
    out["note_count"] = len(case.notes)
    out["signal_note"] = SIGNAL_NOTE
    if with_notes:
        out["notes"] = [{"id": n.id, "author_id": n.author_id, "body": n.body, "created_at": n.created_at}
                        for n in case.notes]
    return out


def list_cases(session: Session, *, status=None, severity=None, source_type=None, assigned_to=None, search=None,
               page=1, page_size=20):
    q = select(Case)
    if status:
        q = q.where(Case.status == status)
    if severity:
        q = q.where(Case.severity == severity)
    if source_type:
        q = q.where(Case.source_type == source_type)
    if assigned_to == "unassigned":
        q = q.where(Case.assigned_to.is_(None))
    elif assigned_to:
        q = q.where(Case.assigned_to == assigned_to)
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where(or_(Case.summary.ilike(like, escape="\\"), Case.case_reference.ilike(like, escape="\\")))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rank = sql_case((Case.severity == "critical", 0), (Case.severity == "high", 1), (Case.severity == "medium", 2),
                    else_=3)
    rows = session.scalars(q.order_by(rank, Case.created_at.desc(), Case.id.desc())
                           .limit(page_size).offset((page - 1) * page_size)).all()
    return rows, total


def get_case(session: Session, case_id: int) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


def create_manual(session: Session, user, *, summary: str, severity: str, evidence_reference: str,
                  correlation_id=None) -> Case:
    if severity not in SEVERITIES:
        raise HTTPException(422, "severity must be low, medium, high or critical")
    case = Case(case_reference=_placeholder_reference(), source_type="manual", source_record_id="manual-" + uuid.uuid4().hex,
                severity=severity, summary=summary[:500], evidence_reference=evidence_reference[:300],
                created_by=user.id)
    session.add(case)
    session.flush()
    case.case_reference = f"CASE-{case.id:06d}"
    record_audit(session, actor=user, action="case.created", entity_type="case", entity_id=case.id,
                 after={"reference": case.case_reference, "source_type": "manual", "severity": severity},
                 correlation_id=correlation_id)
    return case


def update_case(session: Session, user, case: Case, *, status=None, assigned_to=UNSET, note=None, severity=None,
                correlation_id=None) -> Case:
    if not perm.can_handle_case(user.role, case.source_type):
        raise HTTPException(403, "Your role does not handle this kind of case")
    is_admin = user.role == perm.ADMIN
    before = {"status": case.status, "assigned_to": case.assigned_to, "severity": case.severity}

    if assigned_to != UNSET:
        target = assigned_to or None
        if target != case.assigned_to:
            if target is not None and target != user.id and not perm.allowed(user.role, "cases.assign_any"):
                raise HTTPException(403, "You can only assign a case to yourself")
            if target is None and case.assigned_to not in (None, user.id) and not is_admin:
                raise HTTPException(403, "Only the assignee or an administrator can unassign this case")
            case.assigned_to = target
            record_audit(session, actor=user, action="case.assigned", entity_type="case", entity_id=case.id,
                         before={"assigned_to": before["assigned_to"]}, after={"assigned_to": target},
                         correlation_id=correlation_id)

    if severity and severity != case.severity:
        if severity not in SEVERITIES:
            raise HTTPException(422, "invalid severity")
        case.severity = severity
        record_audit(session, actor=user, action="case.severity_changed", entity_type="case", entity_id=case.id,
                     before={"severity": before["severity"]}, after={"severity": severity},
                     correlation_id=correlation_id)

    if status and status != case.status:
        if status not in STATUSES:
            raise HTTPException(422, "invalid status")
        if before["status"] in CLOSED and not is_admin:
            raise HTTPException(403, "Only an administrator can reopen a closed case")
        if status in CLOSED or status == "confirmed":
            if case.assigned_to not in (None, user.id) and not is_admin:
                raise HTTPException(403, "Only the assignee or an administrator can decide this case")
            if case.assigned_to is None:
                case.assigned_to = user.id          # whoever decides the case owns it
        case.status = status
        case.resolved_at = utcnow() if status in CLOSED else None
        record_audit(session, actor=user, action="case.status_changed", entity_type="case", entity_id=case.id,
                     before={"status": before["status"]}, after={"status": status}, correlation_id=correlation_id)

    if note:
        session.add(CaseNote(case_id=case.id, author_id=user.id, body=note))
        record_audit(session, actor=user, action="case.note_added", entity_type="case", entity_id=case.id,
                     after={"note_length": len(note)}, correlation_id=correlation_id)
    case.updated_at = utcnow()
    session.flush()
    session.refresh(case)
    return case
