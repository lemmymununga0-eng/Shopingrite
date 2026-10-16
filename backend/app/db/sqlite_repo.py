"""SQLite repository for local development and automated tests.

Ownership is enforced here in code (the Supabase backend enforces the same rules with RLS):
customers only see their own rows; analysts/admins see all rows and may review alerts.
"""
import json
import sqlite3
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..auth import User
from .base import ListFilters, RepositoryError
from .stats import FIELDS, compute_stats, since_iso

SORT_COLUMNS = {"created_at": "created_at", "amount": "amount", "probability": "probability",
                "risk": "probability", "transaction_reference": "transaction_reference"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  transaction_reference TEXT NOT NULL,
  amount REAL NOT NULL,
  payment_method TEXT NOT NULL,
  hour INTEGER NOT NULL,
  failed_attempts INTEGER NOT NULL,
  new_device INTEGER NOT NULL,
  international INTEGER NOT NULL,
  customer_avg_spend REAL NOT NULL,
  branch TEXT NOT NULL,
  probability REAL NOT NULL,
  risk TEXT NOT NULL,
  prediction TEXT NOT NULL,
  is_flagged INTEGER NOT NULL,
  model_version TEXT NOT NULL,
  contributing_factors TEXT NOT NULL,
  review_status TEXT CHECK (review_status IN ('new','confirmed_fraud','false_positive')),
  review_notes TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tx_flagged ON transactions(is_flagged, review_status);
"""


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("new_device", "international", "is_flagged"):
        d[k] = bool(d[k])
    d["contributing_factors"] = json.loads(d["contributing_factors"])
    return d


class SqliteRepository:
    def __init__(self, path: Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        """Open a connection, commit on success, roll back on error, ALWAYS close."""
        try:
            c = sqlite3.connect(self.path, timeout=10)
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc))
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _scope(user: User):
        return ("1=1", []) if user.can_view_all else ("user_id = ?", [user.id])

    def create_transaction(self, user: User, record: dict) -> dict:
        row = {
            **record,
            "id": str(uuid.uuid4()),
            "user_id": user.id,                       # always the verified token's subject
            "created_at": datetime.now(timezone.utc).isoformat(),
            "review_status": "new" if record["is_flagged"] else None,
            "contributing_factors": json.dumps(record["contributing_factors"]),
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        try:
            with self._conn() as c:
                c.execute(f"INSERT INTO transactions ({cols}) VALUES ({marks})", list(row.values()))
                saved = c.execute("SELECT * FROM transactions WHERE id = ?", (row["id"],)).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc))
        return _row(saved)

    def list_transactions(self, user: User, f: ListFilters):
        where, params = self._scope(user)
        if f.search:
            where += " AND transaction_reference LIKE ? ESCAPE '\\'"
            params.append("%" + f.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if f.risk:
            where += " AND risk = ?"
            params.append(f.risk)
        if f.flagged_only:
            where += " AND is_flagged = 1"
        if f.review_status:
            where += " AND review_status = ?"
            params.append(f.review_status)
        if f.payment_method:
            where += " AND payment_method = ?"
            params.append(f.payment_method)
        if f.date_from:
            where += " AND created_at >= ?"
            params.append(f.date_from)
        if f.date_to_exclusive:
            where += " AND created_at < ?"
            params.append(f.date_to_exclusive)
        column = SORT_COLUMNS.get(f.sort_by, "created_at")          # whitelist: never interpolate user text
        direction = "ASC" if f.sort_dir == "asc" else "DESC"
        try:
            with self._conn() as c:
                total = c.execute(f"SELECT COUNT(*) FROM transactions WHERE {where}", params).fetchone()[0]
                rows = c.execute(
                    f"SELECT * FROM transactions WHERE {where} ORDER BY {column} {direction}, created_at DESC LIMIT ? OFFSET ?",
                    params + [f.page_size, (f.page - 1) * f.page_size]).fetchall()
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc))
        return [_row(r) for r in rows], total

    def get_transaction(self, user: User, transaction_id: str):
        where, params = self._scope(user)
        try:
            with self._conn() as c:
                r = c.execute(f"SELECT * FROM transactions WHERE id = ? AND {where}",
                              [transaction_id] + params).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc))
        return _row(r) if r else None

    def review_alert(self, user: User, transaction_id: str, status: str, notes: str | None):
        if not user.can_review:
            return None
        try:
            with self._conn() as c:
                cur = c.execute(
                    "UPDATE transactions SET review_status = ?, review_notes = ?, reviewed_by = ?, reviewed_at = ? "
                    "WHERE id = ? AND is_flagged = 1",
                    (status, notes, user.id, datetime.now(timezone.utc).isoformat(), transaction_id))
                if cur.rowcount == 0:
                    return None
                r = c.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc))
        return _row(r)

    def stats(self, user: User, days: int | None = None) -> dict:
        where, params = self._scope(user)
        since = since_iso(days)
        if since:
            where += " AND created_at >= ?"
            params = params + [since]
        try:
            with self._conn() as c:
                rows = [dict(r) for r in c.execute(f"SELECT {FIELDS} FROM transactions WHERE {where}", params)]
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc))
        for r in rows:
            r["is_flagged"] = bool(r["is_flagged"])
        return compute_stats(rows, days)
