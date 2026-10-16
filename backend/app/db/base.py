"""Repository interface. Routers depend on this, not on a particular database."""
from dataclasses import dataclass
from typing import Protocol

from ..auth import User


class RepositoryError(Exception):
    """Database unreachable or returned an unexpected error."""


@dataclass
class ListFilters:
    search: str | None = None
    risk: str | None = None
    flagged_only: bool = False
    review_status: str | None = None
    payment_method: str | None = None
    date_from: str | None = None        # YYYY-MM-DD, inclusive
    date_to_exclusive: str | None = None  # YYYY-MM-DD, exclusive (the day after the chosen end date)
    sort_by: str = "created_at"
    sort_dir: str = "desc"
    page: int = 1
    page_size: int = 20


class Repository(Protocol):
    def create_transaction(self, user: User, record: dict) -> dict: ...
    def list_transactions(self, user: User, f: ListFilters) -> tuple[list[dict], int]: ...
    def get_transaction(self, user: User, transaction_id: str) -> dict | None: ...
    def review_alert(self, user: User, transaction_id: str, status: str, notes: str | None) -> dict | None: ...
    def stats(self, user: User, days: int | None = None) -> dict: ...
