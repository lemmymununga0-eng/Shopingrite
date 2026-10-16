from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..ml.feature_schema import BRANCHES, PAYMENT_METHODS  # noqa: F401  (kept for documentation)

PaymentMethod = Literal["Card", "Bank Transfer", "Mobile Money"]
Branch = Literal["Online", "Johannesburg CBD", "Cape Town V&A", "Durban North", "Pretoria Central"]
ReviewStatus = Literal["new", "confirmed_fraud", "false_positive"]


class PredictRequest(BaseModel):
    """What the client may send. Note: no score, risk, prediction or user id fields exist."""
    model_config = ConfigDict(extra="forbid")

    transaction_reference: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    amount: float = Field(ge=0.01, le=1_000_000)
    payment_method: PaymentMethod
    hour: int = Field(ge=0, le=23)
    failed_attempts: int = Field(ge=0, le=10)
    new_device: bool
    international: bool
    customer_avg_spend: float = Field(ge=0, le=1_000_000)
    branch: Branch


class TransactionOut(BaseModel):
    id: str
    user_id: str
    transaction_reference: str
    amount: float
    payment_method: str
    hour: int
    failed_attempts: int
    new_device: bool
    international: bool
    customer_avg_spend: float
    branch: str
    probability: float
    risk: str
    prediction: str
    is_flagged: bool
    model_version: str
    contributing_factors: list[str]
    review_status: ReviewStatus | None = None
    review_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class PredictResponse(BaseModel):
    transaction: TransactionOut
    saved: bool = True
    explanation_note: str = ("Contributing factors are simple rule checks on the submitted values. "
                             "They are not an explanation of the model's internal decision.")


class Page(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int


class AlertReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReviewStatus
    notes: str | None = Field(default=None, max_length=1000)


class DailyPoint(BaseModel):
    date: str
    total: int
    flagged: int


class Stats(BaseModel):
    total_transactions: int
    flagged: int
    lower_risk: int
    total_amount: float
    open_alerts: int
    confirmed_fraud: int
    false_positive: int
    reviewed: int
    avg_probability: float | None
    flag_rate: float | None          # flagged / total (model flags, NOT confirmed fraud)
    risk_counts: dict[str, int]
    daily: list[DailyPoint]
    period_days: int | None
