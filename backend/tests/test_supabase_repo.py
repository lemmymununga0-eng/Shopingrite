"""MOCKED tests of the Supabase repository: they check the HTTP requests we send, using httpx.MockTransport.
They do NOT prove anything about a live Supabase project or its RLS policies (see docs/TEST_RESULTS.md)."""
import json

import httpx
import pytest

from app.auth import User
from app.db.base import ListFilters, RepositoryError
from app.db.supabase_repo import SupabaseRepository

U = User(id="u1", email=None, role="customer", token="tok123")
R = User(id="r1", email=None, role="analyst", token="rtok")


def repo_with(handler):
    return SupabaseRepository("https://x.supabase.co", "anon-key", httpx.Client(transport=httpx.MockTransport(handler)))


def test_requires_url_and_key():
    with pytest.raises(RepositoryError):
        SupabaseRepository("", "")


def test_insert_sends_user_token_and_verified_user_id():
    seen = {}

    def h(req):
        seen["auth"], seen["apikey"] = req.headers["authorization"], req.headers["apikey"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json=[{"id": "1", **seen["body"]}])

    repo_with(h).create_transaction(U, {"is_flagged": True, "transaction_reference": "T1", "user_id": "evil"})
    assert seen["auth"] == "Bearer tok123" and seen["apikey"] == "anon-key"
    assert seen["body"]["user_id"] == "u1" and seen["body"]["review_status"] == "new"


def test_list_builds_filters_and_reads_count():
    seen = {}

    def h(req):
        seen["q"] = dict(req.url.params)
        return httpx.Response(200, json=[], headers={"content-range": "0-19/45"})

    items, total = repo_with(h).list_transactions(U, ListFilters(search="AB*C),", risk="High", flagged_only=True, page=2, page_size=20))
    assert total == 45 and seen["q"]["offset"] == "20" and seen["q"]["transaction_reference"] == "ilike.*ABC*"
    assert seen["q"]["risk"] == "eq.High" and seen["q"]["is_flagged"] == "eq.true"


def test_review_patch_and_customer_blocked_locally():
    seen = {}

    def h(req):
        seen["method"], seen["body"] = req.method, json.loads(req.content)
        return httpx.Response(200, json=[{"id": "1"}])

    r = repo_with(h)
    assert r.review_alert(R, "1", "confirmed_fraud", "n") == {"id": "1"}
    assert seen["method"] == "PATCH" and seen["body"]["reviewed_by"] == "r1"
    assert r.review_alert(U, "1", "confirmed_fraud", None) is None


def test_errors_become_repository_error():
    with pytest.raises(RepositoryError):
        repo_with(lambda req: httpx.Response(401, json={})).stats(U)

    def boom(req):
        raise httpx.ConnectError("no route")

    with pytest.raises(RepositoryError):
        repo_with(boom).stats(U)


def test_stats_aggregation_and_request():
    rows = [{"amount": 10, "is_flagged": True, "review_status": "new", "risk": "High", "probability": 0.9, "created_at": "2026-10-15T10:00:00+00:00"},
            {"amount": 5.5, "is_flagged": False, "review_status": None, "risk": "Low", "probability": 0.1, "created_at": "2026-10-15T11:00:00+00:00"}]
    seen = {}

    def h(req):
        seen["q"] = req.url.params.multi_items()
        return httpx.Response(200, json=rows)

    s = repo_with(h).stats(U)
    assert s["total_transactions"] == 2 and s["flagged"] == 1 and s["total_amount"] == 15.5 and s["open_alerts"] == 1
    assert s["risk_counts"] == {"Low": 1, "Medium": 0, "High": 1} and s["avg_probability"] == 0.5 and s["flag_rate"] == 0.5
    repo_with(h).stats(U, days=7)
    assert any(k == "created_at" and v.startswith("gte.") for k, v in seen["q"])


def test_list_sends_date_method_and_sort_params():
    seen = {}

    def h(req):
        seen["q"] = req.url.params.multi_items()
        return httpx.Response(200, json=[], headers={"content-range": "*/0"})

    repo_with(h).list_transactions(U, ListFilters(payment_method="Card", date_from="2026-10-01", date_to_exclusive="2026-10-16",
                                                  sort_by="amount", sort_dir="asc"))
    q = seen["q"]
    assert ("order", "amount.asc") in q and ("payment_method", "eq.Card") in q
    assert ("created_at", "gte.2026-10-01") in q and ("created_at", "lt.2026-10-16") in q
