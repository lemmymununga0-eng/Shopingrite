"""Supabase repository using PostgREST.

Every request carries the CALLER'S access token plus the public anon key, so Postgres Row Level
Security (see supabase/migrations) decides what the caller can read or change. The service-role
key is deliberately never used by this application.
"""
import re

import httpx

from ..auth import User
from .base import ListFilters, RepositoryError
from .stats import FIELDS, compute_stats, since_iso

TABLE = "transactions"


class SupabaseRepository:
    def __init__(self, url: str, anon_key: str, client: httpx.Client | None = None):
        if not url or not anon_key:
            raise RepositoryError("SUPABASE_URL and SUPABASE_ANON_KEY must be set for DB_BACKEND=supabase")
        self.base = url.rstrip("/") + "/rest/v1/" + TABLE
        self.anon_key = anon_key
        self.client = client or httpx.Client(timeout=10)

    def _headers(self, user: User, **extra):
        return {"apikey": self.anon_key, "Authorization": f"Bearer {user.token}",
                "Content-Type": "application/json", **extra}

    def _send(self, method: str, user: User, params=None, json=None, prefer: str | None = None):
        headers = self._headers(user, **({"Prefer": prefer} if prefer else {}))
        try:
            r = self.client.request(method, self.base, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise RepositoryError(f"Database unreachable ({type(exc).__name__})")
        if r.status_code >= 400:
            raise RepositoryError(f"Database error {r.status_code}")
        return r

    def create_transaction(self, user: User, record: dict) -> dict:
        row = {**record, "user_id": user.id,
               "review_status": "new" if record["is_flagged"] else None}
        r = self._send("POST", user, json=row, prefer="return=representation")
        data = r.json()
        if not data:
            raise RepositoryError("Insert returned no row")
        return data[0]

    def list_transactions(self, user: User, f: ListFilters):
        sort = {"created_at": "created_at", "amount": "amount", "probability": "probability",
                "risk": "probability", "transaction_reference": "transaction_reference"}.get(f.sort_by, "created_at")
        params = [("select", "*"), ("order", f"{sort}.{'asc' if f.sort_dir == 'asc' else 'desc'}"),
                  ("limit", str(f.page_size)), ("offset", str((f.page - 1) * f.page_size))]
        if f.search:
            safe = re.sub(r"[^A-Za-z0-9._-]", "", f.search)
            if safe:
                params.append(("transaction_reference", f"ilike.*{safe}*"))
        if f.risk:
            params.append(("risk", f"eq.{f.risk}"))
        if f.flagged_only:
            params.append(("is_flagged", "eq.true"))
        if f.review_status:
            params.append(("review_status", f"eq.{f.review_status}"))
        if f.payment_method:
            params.append(("payment_method", f"eq.{f.payment_method}"))
        if f.date_from:
            params.append(("created_at", f"gte.{f.date_from}"))
        if f.date_to_exclusive:
            params.append(("created_at", f"lt.{f.date_to_exclusive}"))
        r = self._send("GET", user, params=params, prefer="count=exact")
        total = int(r.headers.get("content-range", "*/0").split("/")[-1] or 0)
        return r.json(), total

    def get_transaction(self, user: User, transaction_id: str):
        r = self._send("GET", user, params={"select": "*", "id": f"eq.{transaction_id}"})
        data = r.json()
        return data[0] if data else None

    def review_alert(self, user: User, transaction_id: str, status: str, notes: str | None):
        if not user.can_review:
            return None
        from datetime import datetime, timezone
        body = {"review_status": status, "review_notes": notes, "reviewed_by": user.id,
                "reviewed_at": datetime.now(timezone.utc).isoformat()}
        r = self._send("PATCH", user, params={"id": f"eq.{transaction_id}", "is_flagged": "eq.true"},
                       json=body, prefer="return=representation")
        data = r.json()
        return data[0] if data else None

    def stats(self, user: User, days: int | None = None) -> dict:
        params = [("select", FIELDS), ("limit", "10000")]
        since = since_iso(days)
        if since:
            params.append(("created_at", f"gte.{since}"))
        r = self._send("GET", user, params=params)
        return compute_stats(r.json(), days)
