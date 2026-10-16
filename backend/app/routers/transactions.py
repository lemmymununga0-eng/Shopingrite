import logging
import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import User, current_user, require_reviewer
from ..db.base import ListFilters, Repository, RepositoryError
from ..dependencies import get_predictor, get_repo, predict_rate_limit
from ..ml.predict import ModelUnavailable, Predictor
from ..schemas.transactions import AlertReview, Page, PredictRequest, PredictResponse, Stats, TransactionOut

log = logging.getLogger("fraudguard")
router = APIRouter()


def _db_error(exc: RepositoryError):
    log.error("database error: %s", exc)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The database is unavailable. Try again shortly.")


def _valid_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _parse_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{name} must be a date like 2026-10-15")


def _filters(search, risk, review_status, page, page_size, flagged_only=False, payment_method=None,
             date_from=None, date_to=None, sort_by="created_at", sort_dir="desc") -> ListFilters:
    if risk not in (None, "", "Low", "Medium", "High"):
        raise HTTPException(422, "risk must be Low, Medium or High")
    if review_status not in (None, "", "new", "confirmed_fraud", "false_positive"):
        raise HTTPException(422, "invalid review_status")
    if payment_method not in (None, "", "Card", "Bank Transfer", "Mobile Money"):
        raise HTTPException(422, "invalid payment_method")
    if sort_by not in ("created_at", "amount", "probability", "risk", "transaction_reference"):
        raise HTTPException(422, "invalid sort_by")
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(422, "sort_dir must be asc or desc")
    d_from, d_to = _parse_date(date_from, "date_from"), _parse_date(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(422, "date_from must not be after date_to")
    return ListFilters(search=(search or None), risk=risk or None, flagged_only=flagged_only,
                       review_status=review_status or None, payment_method=payment_method or None,
                       date_from=d_from.isoformat() if d_from else None,
                       date_to_exclusive=(d_to + timedelta(days=1)).isoformat() if d_to else None,
                       sort_by=sort_by, sort_dir=sort_dir, page=page, page_size=page_size)


Search = Annotated[str | None, Query(max_length=40)]
PageNo = Annotated[int, Query(ge=1, le=10000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.post("/predict", response_model=PredictResponse, status_code=201, tags=["predict"])
def predict(payload: PredictRequest, user: User = Depends(predict_rate_limit),
            predictor: Predictor = Depends(get_predictor), repo: Repository = Depends(get_repo)):
    features = {
        "amount": payload.amount, "hour": payload.hour, "failed_attempts": payload.failed_attempts,
        "new_device": int(payload.new_device), "international": int(payload.international),
        "customer_avg_spend": payload.customer_avg_spend, "payment_method": payload.payment_method,
        "branch": payload.branch,
    }
    try:
        result = predictor.predict(features)
    except ModelUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Model unavailable: {exc}")
    record = {
        "transaction_reference": payload.transaction_reference, **features,
        "new_device": payload.new_device, "international": payload.international,
        "probability": round(result.probability, 6), "risk": result.risk,
        "prediction": "Potential Fraud" if result.is_fraud else "Likely Legitimate",
        "is_flagged": result.is_fraud, "model_version": result.model_version,
        "contributing_factors": result.contributing_factors,
    }
    try:
        saved = repo.create_transaction(user, record)
    except RepositoryError as exc:
        raise _db_error(exc)
    return PredictResponse(transaction=saved)


@router.get("/transactions", response_model=Page, tags=["transactions"])
def list_transactions(search: Search = None, risk: str | None = None, review_status: str | None = None,
                      payment_method: str | None = None, date_from: str | None = None, date_to: str | None = None,
                      sort_by: str = "created_at", sort_dir: str = "desc",
                      page: PageNo = 1, page_size: PageSize = 20,
                      user: User = Depends(current_user), repo: Repository = Depends(get_repo)):
    f = _filters(search, risk, review_status, page, page_size, False, payment_method, date_from, date_to, sort_by, sort_dir)
    try:
        items, total = repo.list_transactions(user, f)
    except RepositoryError as exc:
        raise _db_error(exc)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/transactions/stats", response_model=Stats, tags=["transactions"])
def stats(days: Annotated[int | None, Query(ge=1, le=365)] = None,
          user: User = Depends(current_user), repo: Repository = Depends(get_repo)):
    try:
        return repo.stats(user, days)
    except RepositoryError as exc:
        raise _db_error(exc)


@router.get("/transactions/{transaction_id}", response_model=TransactionOut, tags=["transactions"])
def get_transaction(transaction_id: str, user: User = Depends(current_user), repo: Repository = Depends(get_repo)):
    try:
        item = repo.get_transaction(user, _valid_id(transaction_id))
    except RepositoryError as exc:
        raise _db_error(exc)
    if item is None:       # same answer for "missing" and "belongs to someone else"
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return item


@router.get("/alerts", response_model=Page, tags=["alerts"])
def list_alerts(search: Search = None, risk: str | None = None, review_status: str | None = None,
                date_from: str | None = None, date_to: str | None = None,
                sort_by: str = "created_at", sort_dir: str = "desc",
                page: PageNo = 1, page_size: PageSize = 20,
                user: User = Depends(current_user), repo: Repository = Depends(get_repo)):
    f = _filters(search, risk, review_status, page, page_size, True, None, date_from, date_to, sort_by, sort_dir)
    try:
        items, total = repo.list_transactions(user, f)
    except RepositoryError as exc:
        raise _db_error(exc)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.patch("/alerts/{alert_id}", response_model=TransactionOut, tags=["alerts"])
def review_alert(alert_id: str, body: AlertReview, user: User = Depends(require_reviewer),
                 repo: Repository = Depends(get_repo)):
    try:
        item = repo.review_alert(user, _valid_id(alert_id), body.status, body.notes)
    except RepositoryError as exc:
        raise _db_error(exc)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    return item
