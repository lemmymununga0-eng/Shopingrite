"""Prediction repository on the application database (SQLite file locally, PostgreSQL in production).

Selected with DB_BACKEND=app. It gives the staff 'New Payment' history the same durability as orders and cases, with no
second database. Ownership is enforced here in code, exactly as in the SQLite repository: customers see their own rows,
staff see all rows and only reviewers may review alerts.
"""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from ..auth import User
from .base import ListFilters, RepositoryError
from .models import PredictionRecord
from .stats import compute_stats, since_iso

SORT_COLUMNS = {"created_at": PredictionRecord.created_at, "amount": PredictionRecord.amount,
                "probability": PredictionRecord.probability, "risk": PredictionRecord.probability,
                "transaction_reference": PredictionRecord.transaction_reference}
COLUMNS = [c.name for c in PredictionRecord.__table__.columns]


def _row(r: PredictionRecord) -> dict:
    d = {c: getattr(r, c) for c in COLUMNS}
    d["contributing_factors"] = json.loads(d["contributing_factors"] or "[]")
    return d


class AppRepository:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _scope(user: User):
        return [] if user.can_view_all else [PredictionRecord.user_id == user.id]

    def create_transaction(self, user: User, record: dict) -> dict:
        row = PredictionRecord(**{**record, "id": str(uuid.uuid4()), "user_id": user.id,
                                  "created_at": datetime.now(timezone.utc).isoformat(),
                                  "review_status": "new" if record["is_flagged"] else None,
                                  "contributing_factors": json.dumps(record["contributing_factors"])})
        try:
            with self.db.session() as s:
                s.add(row)
                s.flush()
                return _row(row)
        except SQLAlchemyError as exc:
            raise RepositoryError(str(exc))

    def _filters(self, user: User, f: ListFilters):
        P, w = PredictionRecord, self._scope(user)
        if f.search:
            like = "%" + f.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            w.append(P.transaction_reference.like(like, escape="\\"))
        if f.risk:
            w.append(P.risk == f.risk)
        if f.flagged_only:
            w.append(P.is_flagged.is_(True))
        if f.review_status:
            w.append(P.review_status == f.review_status)
        if f.payment_method:
            w.append(P.payment_method == f.payment_method)
        if f.date_from:
            w.append(P.created_at >= f.date_from)
        if f.date_to_exclusive:
            w.append(P.created_at < f.date_to_exclusive)
        return w

    def list_transactions(self, user: User, f: ListFilters):
        P, where = PredictionRecord, self._filters(user, f)
        col = SORT_COLUMNS.get(f.sort_by, P.created_at)            # whitelist: never interpolate user text
        order = col.asc() if f.sort_dir == "asc" else col.desc()
        try:
            with self.db.session() as s:
                total = s.scalar(select(func.count()).select_from(P).where(*where)) or 0
                rows = s.scalars(select(P).where(*where).order_by(order, P.created_at.desc())
                                 .limit(f.page_size).offset((f.page - 1) * f.page_size)).all()
                return [_row(r) for r in rows], total
        except SQLAlchemyError as exc:
            raise RepositoryError(str(exc))

    def get_transaction(self, user: User, transaction_id: str):
        try:
            with self.db.session() as s:
                r = s.scalar(select(PredictionRecord).where(PredictionRecord.id == transaction_id, *self._scope(user)))
                return _row(r) if r else None
        except SQLAlchemyError as exc:
            raise RepositoryError(str(exc))

    def review_alert(self, user: User, transaction_id: str, status: str, notes: str | None):
        if not user.can_review:
            return None
        P = PredictionRecord
        try:
            with self.db.session() as s:
                n = s.execute(update(P).where(P.id == transaction_id, P.is_flagged.is_(True))
                              .values(review_status=status, review_notes=notes, reviewed_by=user.id,
                                      reviewed_at=datetime.now(timezone.utc).isoformat())).rowcount
                if n == 0:
                    return None
                return _row(s.scalar(select(P).where(P.id == transaction_id)))
        except SQLAlchemyError as exc:
            raise RepositoryError(str(exc))

    def stats(self, user: User, days: int | None = None) -> dict:
        P, where = PredictionRecord, self._scope(user)
        since = since_iso(days)
        if since:
            where.append(P.created_at >= since)
        try:
            with self.db.session() as s:
                rows = [{"amount": r.amount, "is_flagged": bool(r.is_flagged), "review_status": r.review_status, "risk": r.risk,
                         "probability": r.probability, "created_at": r.created_at}
                        for r in s.execute(select(P.amount, P.is_flagged, P.review_status, P.risk, P.probability, P.created_at).where(*where))]
        except SQLAlchemyError as exc:
            raise RepositoryError(str(exc))
        return compute_stats(rows, days)
