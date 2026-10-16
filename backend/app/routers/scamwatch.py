"""ScamWatch endpoints. The submitted URL is analysed as data and is never fetched by the server."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..auth import User, require
from ..dependencies import correlation, get_session, limited
from ..services import scamwatch_service as sw

router = APIRouter(prefix="/scamwatch", tags=["scamwatch"])
guard = Depends(limited("scamwatch", "scamwatch_rate_limit_per_min"))


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


class ReportRequest(CheckRequest):
    comment: str = Field(default="", max_length=1000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_status: Literal["pending", "reviewed_malicious", "reviewed_benign", "dismissed"]
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/check", dependencies=[guard])
def check(body: CheckRequest, request: Request, user: User = Depends(require("scamwatch.check"))):
    try:
        normalized, domain, notes = sw.normalize_url(body.url)
    except sw.InvalidUrl as exc:
        request.app.state.events.record("info", "input", "input.invalid_url", "Rejected a malformed URL in ScamWatch",
                                        actor_id=user.id, path=request.url.path, method="POST", status_code=422,
                                        correlation_id=correlation(request), dedupe=True)
        raise HTTPException(422, str(exc))
    return sw.run_check(normalized, domain, notes, request.app.state.providers, request.app.state.events,
                        correlation(request))


@router.post("/reports", status_code=201, dependencies=[guard])
def create_report(body: ReportRequest, request: Request, response: Response,
                  user: User = Depends(require("scamwatch.check"))):
    with request.app.state.db.session() as session:
        report, duplicate, check_result = sw.submit_report(session, user, body.url, body.comment,
                                                           request.app.state.providers, request.app.state.events,
                                                           correlation(request))
        out = sw.report_out(report, include_notes=user.has("scamwatch.view_all"))
    if duplicate:
        response.status_code = 200
    return {"duplicate": duplicate, "report": out, "check": check_result,
            "message": ("This website was already reported; your report was added to the count." if duplicate
                        else "Thank you. The report was saved for review.")}


@router.get("/reports")
def list_reports(review_status: Annotated[str | None, Query(pattern=r"^[a-z_]+$", max_length=24)] = None,
                 verdict: Annotated[str | None, Query(pattern=r"^[a-z_]+$", max_length=20)] = None,
                 search: Annotated[str | None, Query(max_length=60)] = None,
                 page: Annotated[int, Query(ge=1, le=10000)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
                 user: User = Depends(require("scamwatch.check")), session=Depends(get_session)):
    rows, total = sw.list_reports(session, user, review_status=review_status, verdict=verdict, search=search,
                                  page=page, page_size=page_size)
    staff = user.has("scamwatch.view_all")
    return {"items": [sw.report_out(r, staff) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/reports/{report_id}")
def read_report(report_id: int, user: User = Depends(require("scamwatch.check")), session=Depends(get_session)):
    return sw.report_out(sw.get_report(session, user, report_id), user.has("scamwatch.view_all"))


@router.patch("/reports/{report_id}")
def review(report_id: int, body: ReviewRequest, request: Request, user: User = Depends(require("scamwatch.review"))):
    with request.app.state.db.session() as session:
        report = sw.review_report(session, user, report_id, body.review_status, body.notes, correlation(request))
        return sw.report_out(report, True)


@router.get("/providers")
def providers(request: Request, user: User = Depends(require("scamwatch.view_all"))):
    return {"providers": sw.provider_status(request.app.state.settings), "disclaimer": sw.DISCLAIMER}
