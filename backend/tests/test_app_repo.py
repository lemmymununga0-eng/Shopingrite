"""DB_BACKEND=app: staff predictions stored in the application database (durable on PostgreSQL hosts).
The same API behaviour as the SQLite repository: ownership, review rights, filters, sorting and stats."""
import pytest
from fastapi.testclient import TestClient

from app.factory import create_app

from .conftest import RISKY, auth, valid_payload

ANALYST = lambda: auth("analyst-1", "fraud_analyst")      # noqa: E731
OTHER = lambda: auth("analyst-2", "fraud_analyst")        # noqa: E731


@pytest.fixture()
def app_client(settings):
    settings.db_backend = "app"
    with TestClient(create_app(settings)) as c:
        yield c


def test_uses_the_application_database_and_reports_it(app_client):
    assert app_client.get("/health").json()["db_backend"] == "app"


def test_predict_saves_and_the_record_is_listed_and_readable(app_client):
    r = app_client.post("/predict", json=valid_payload(transaction_reference="TX-APP-1"), headers=ANALYST())
    assert r.status_code == 201, r.text
    tid = r.json()["transaction"]["id"]
    listed = app_client.get("/transactions", headers=ANALYST()).json()
    assert listed["total"] == 1 and listed["items"][0]["transaction_reference"] == "TX-APP-1"
    one = app_client.get(f"/transactions/{tid}", headers=ANALYST()).json()
    assert one["amount"] == 250.0 and one["new_device"] is False and isinstance(one["contributing_factors"], list)


def test_flagged_payments_start_as_new_alerts_and_can_be_reviewed_only_by_reviewers(app_client):
    tid = app_client.post("/predict", json=valid_payload(transaction_reference="TX-APP-2", **RISKY), headers=ANALYST()).json()["transaction"]["id"]
    alerts = app_client.get("/alerts", headers=ANALYST()).json()
    assert alerts["total"] == 1 and alerts["items"][0]["review_status"] == "new"
    assert app_client.patch(f"/alerts/{tid}", json={"status": "false_positive"}, headers=auth("sec-1", "security_analyst")).status_code == 403
    r = app_client.patch(f"/alerts/{tid}", json={"status": "confirmed_fraud", "notes": "called the customer"}, headers=ANALYST())
    assert r.status_code == 200 and r.json()["review_status"] == "confirmed_fraud" and r.json()["review_notes"] == "called the customer"
    assert r.json()["reviewed_by"] == "analyst-1"
    assert app_client.get("/alerts?review_status=confirmed_fraud", headers=ANALYST()).json()["total"] == 1


def test_customers_cannot_use_staff_prediction_endpoints_or_see_others(app_client):
    app_client.post("/predict", json=valid_payload(transaction_reference="TX-APP-3"), headers=ANALYST())
    cust = auth("cust-1", "customer")
    assert app_client.get("/transactions", headers=cust).status_code in (200, 403)
    if app_client.get("/transactions", headers=cust).status_code == 200:
        assert app_client.get("/transactions", headers=cust).json()["total"] == 0
    assert app_client.post("/predict", json=valid_payload(), headers=cust).status_code == 403


def test_filters_search_sort_and_paging(app_client):
    for i, amount in enumerate((100.0, 900.0, 400.0)):
        app_client.post("/predict", json=valid_payload(transaction_reference=f"TX-F-{i}", amount=amount), headers=ANALYST())
    assert app_client.get("/transactions?search=F-1", headers=ANALYST()).json()["total"] == 1
    by_amount = app_client.get("/transactions?sort_by=amount&sort_dir=asc", headers=ANALYST()).json()["items"]
    assert [i["amount"] for i in by_amount] == [100.0, 400.0, 900.0]
    page2 = app_client.get("/transactions?sort_by=amount&sort_dir=desc&page=2&page_size=2", headers=ANALYST()).json()
    assert page2["total"] == 3 and [i["amount"] for i in page2["items"]] == [100.0]
    assert app_client.get("/transactions?search=%25", headers=ANALYST()).json()["total"] == 0           # wildcards are escaped
    assert app_client.get("/transactions?payment_method=Card", headers=ANALYST()).json()["total"] == 3
    assert app_client.get("/transactions?sort_by=amount;DROP TABLE x", headers=ANALYST()).status_code == 422


def test_stats_are_computed_from_stored_rows(app_client):
    app_client.post("/predict", json=valid_payload(transaction_reference="TX-S-1"), headers=ANALYST())
    app_client.post("/predict", json=valid_payload(transaction_reference="TX-S-2", **RISKY), headers=ANALYST())
    s = app_client.get("/transactions/stats", headers=ANALYST()).json()
    assert s["total_transactions"] == 2 and s["flagged"] == 1 and s["open_alerts"] == 1
    assert app_client.get("/transactions/stats?days=7", headers=ANALYST()).json()["total_transactions"] == 2


def test_unknown_ids_are_404(app_client):
    assert app_client.get("/transactions/00000000-0000-0000-0000-000000000000", headers=ANALYST()).status_code == 404
    assert app_client.get("/transactions/not-a-uuid", headers=ANALYST()).status_code == 404


def test_data_survives_an_application_restart(settings):
    settings.db_backend = "app"
    with TestClient(create_app(settings)) as first:
        first.post("/predict", json=valid_payload(transaction_reference="TX-KEEP"), headers=ANALYST())
    with TestClient(create_app(settings)) as second:
        assert second.get("/transactions", headers=ANALYST()).json()["items"][0]["transaction_reference"] == "TX-KEEP"
