"""Investigation Centre: cases from every signal source, with permissions and an audit trail."""
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import User, require
from ..db.base import RepositoryError
from ..db.models import ScamReport, SecurityEvent
from ..dependencies import correlation, get_repo, get_session
from ..services import investigation_service as svc

log = logging.getLogger("fraudguard")
router = APIRouter(prefix="/investigations", tags=["investigations"])

Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["new", "investigating", "confirmed", "false_positive", "resolved"]
SourceType = Literal["fraud_prediction", "scamwatch_report", "security_alert", "order_anomaly", "manual"]


class CaseCreate(BaseModel):
    """Either a manual case (summary + severity) or a promotion of an existing record (source_type + id)."""
    model_config = ConfigDict(extra="forbid")
    source_type: SourceType = "manual"
    source_record_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    summary: str | None = Field(default=None, min_length=3, max_length=500)
    severity: Severity = "medium"
    evidence_reference: str = Field(default="", max_length=300)


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status | None = None
    severity: Severity | None = None
    assigned_to: str | None = Field(default=None, max_length=64)      # "me", a user id, or null to unassign
    note: str | None = Field(default=None, min_length=1, max_length=2000)


def _resolve_source(session, repo, user: User, body: CaseCreate) -> dict:
    """Confirm the referenced record really exists and derive a summary, instead of trusting the client."""
    sid = body.source_record_id
    if body.source_type == "fraud_prediction":
        try:
            tx = repo.get_transaction(user, sid)
        except RepositoryError:
            raise HTTPException(503, "The fraud records are unavailable. Try again shortly.")
        if tx is None:
            raise HTTPException(404, "Prediction not found")
        sev = {"High": "high", "Medium": "medium"}.get(tx["risk"], "low")
        return {"severity": sev, "evidence": f"transaction:{sid}", "summary":
                f"Model score {tx['probability']:.2f} ({tx['risk']} risk) for transaction {tx['transaction_reference']}. "
                f"{svc.SIGNAL_NOTE}"}
    if body.source_type == "scamwatch_report":
        r = session.get(ScamReport, int(sid)) if sid.isdigit() else None
        if r is None:
            raise HTTPException(404, "Report not found")
        return {"severity": "high" if r.verdict == "malicious" else "medium", "evidence": f"scam_report:{r.id}",
                "summary": f"Reported website {r.domain} (verdict: {r.verdict}, {r.report_count} report(s))"}
    if body.source_type == "security_alert":
        e = session.get(SecurityEvent, int(sid)) if sid.isdigit() else None
        if e is None:
            raise HTTPException(404, "Security event not found")
        return {"severity": e.severity if e.severity in svc.SEVERITIES else "low", "evidence": f"security_event:{e.id}",
                "summary": e.message}
    raise HTTPException(422, "Order anomaly cases are created automatically by the order-risk rules")


@router.get("")
def list_cases(status: Status | None = None, severity: Severity | None = None, source_type: SourceType | None = None,
               assigned_to: Annotated[str | None, Query(max_length=64)] = None,
               search: Annotated[str | None, Query(max_length=80)] = None,
               page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
               user: User = Depends(require("cases.view")), session=Depends(get_session)):
    if assigned_to == "me":
        assigned_to = user.id
    rows, total = svc.list_cases(session, status=status, severity=severity, source_type=source_type,
                                 assigned_to=assigned_to, search=search, page=page, page_size=page_size)
    return {"items": [svc.serialize(c) for c in rows], "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_case(body: CaseCreate, request: Request, user: User = Depends(require("cases.create")),
                repo=Depends(get_repo)):
    cid = correlation(request)
    with request.app.state.db.session() as session:
        if body.source_type == "manual":
            if not body.summary:
                raise HTTPException(422, "A summary is required for a manual case")
            case = svc.create_manual(session, user, summary=body.summary, severity=body.severity,
                                     evidence_reference=body.evidence_reference, correlation_id=cid)
            created = True
        else:
            if not body.source_record_id:
                raise HTTPException(422, "source_record_id is required")
            from ..core import permissions as perm
            if not perm.can_handle_case(user.role, body.source_type):
                raise HTTPException(403, "Your role does not handle this kind of case")
            info = _resolve_source(session, repo, user, body)
            case, created = svc.ensure_case(session, source_type=body.source_type, source_record_id=body.source_record_id,
                                            severity=info["severity"], summary=info["summary"],
                                            evidence_reference=info["evidence"], created_by=user.id, correlation_id=cid)
        out = svc.serialize(case, with_notes=True)
    out["already_existed"] = not created
    return out


@router.get("/{case_id}")
def read_case(case_id: int, user: User = Depends(require("cases.view")), session=Depends(get_session)):
    return svc.serialize(svc.get_case(session, case_id), with_notes=True)


@router.patch("/{case_id}")
def update_case(case_id: int, body: CaseUpdate, request: Request, user: User = Depends(require("cases.update")),
                repo=Depends(get_repo)):
    cid = correlation(request)
    assigned = svc.UNSET
    if "assigned_to" in body.model_fields_set:
        assigned = user.id if body.assigned_to == "me" else body.assigned_to
    with request.app.state.db.session() as session:
        case = svc.get_case(session, case_id)
        case = svc.update_case(session, user, case, status=body.status, assigned_to=assigned, note=body.note,
                               severity=body.severity, correlation_id=cid)
        out = svc.serialize(case, with_notes=True)
        source = (case.source_type, case.source_record_id)
    # Keep the older fraud-alert review screen consistent with the case outcome (best effort).
    if source[0] == "fraud_prediction" and body.status in ("confirmed", "false_positive"):
        try:
            repo.review_alert(user, source[1], "confirmed_fraud" if body.status == "confirmed" else "false_positive",
                              body.note)
        except Exception:
            log.warning("could not mirror case outcome to the alert review record")
    return out
