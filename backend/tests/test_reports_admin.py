"""Reports (real stored records), admin users/roles, audit trail, integrations status, migrations, model config."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.migrations import MIGRATIONS, migrate
from app.db.models import AppUser, Product
from app.db.session import Database
from app.factory import create_app
from app.ml.predict import Predictor

from .conftest import RISKY, admin_h, auth, cust, put_in_cart, order_body, valid_payload

FRAUD = lambda: auth("fa-1", "fraud_analyst")  # noqa: E731
SEC = lambda: auth("sa-1", "security_analyst")  # noqa: E731


# ---------------- reports ----------------
def test_overview_on_an_empty_system_shows_zeroes_not_invented_numbers(client):
    d = client.get("/reports/overview", headers=FRAUD()).json()
    assert d["fraud"]["transactions_analysed"] == 0 and d["fraud"]["flagged"] == 0
    assert d["cases"]["open"] == 0 and d["cases"]["recent"] == [] and d["cases"]["resolution"]["average_hours"] is None
    assert d["scamwatch"]["reports"] == 0 and d["orders"]["by_status"] == {}
    assert d["inventory"]["out_of_stock_products"] == 4                        # real seeded stock
    assert d["security"] is None and d["audit"] is None                        # not visible to a fraud analyst
    assert "definitions" in d and "flag is a signal" in d["definitions"]["flagged"]


def test_overview_reflects_stored_records(client):
    t = client.post("/predict", json=valid_payload(**RISKY), headers=FRAUD()).json()["transaction"]
    client.post("/predict", json=valid_payload(transaction_reference="TX-OK"), headers=FRAUD())
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 2)
    client.post("/orders", json=order_body(), headers=h)
    d = client.get("/reports/overview", headers=admin_h()).json()
    assert d["fraud"]["transactions_analysed"] == 2 and d["fraud"]["flagged"] == 1
    assert d["cases"]["open"] == 1 and d["cases"]["by_source"] == {"fraud_prediction": 1}
    assert d["orders"]["by_status"] == {"confirmed": 1} and d["orders"]["revenue_by_currency_cents"]["ZAR"] > 0
    assert "no real money" in d["orders"]["note"].lower()
    assert d["security"] is not None and d["audit"]["events_in_period"] >= 1
    case_id = d["cases"]["recent"][0]["id"]
    client.patch(f"/investigations/{case_id}", json={"status": "resolved"}, headers=FRAUD())
    d2 = client.get("/reports/overview", headers=admin_h()).json()
    assert d2["cases"]["open"] == 0 and d2["cases"]["resolution"]["resolved_cases"] == 1
    assert d2["cases"]["resolution"]["average_hours"] is not None


def test_fraud_report_labels_model_and_hypothetical_baseline(client):
    client.post("/predict", json=valid_payload(**RISKY), headers=FRAUD())
    d = client.get("/reports/fraud?baseline_flag_rate=5&assumed_loss_per_fraud=1000", headers=FRAUD()).json()
    assert d["model"]["is_synthetic"] is True and "say nothing about real fraud" in d["model"]["note"]
    bc = d["baseline_comparison"]
    assert bc["label"].startswith("HYPOTHETICAL") and "not money saved" in bc["note"]
    assert bc["exposure_identified_in_prototype"] == 0.0                      # nothing confirmed yet
    assert "baseline_comparison" not in client.get("/reports/fraud", headers=FRAUD()).json()
    assert client.get("/reports/fraud?baseline_flag_rate=500", headers=FRAUD()).status_code == 422
    assert client.get("/reports/fraud", headers=SEC()).status_code == 403


def test_fraud_report_without_a_model_says_so(client_no_model):
    d = client_no_model.get("/reports/fraud", headers=FRAUD()).json()
    assert d["model"]["available"] is False and "message" in d["model"]


def test_security_report(client):
    client.get("/cart")
    d = client.get("/reports/security", headers=SEC()).json()
    assert d["authentication_failures"] >= 1 and d["daily"] and "not network" in d["definitions"]["security_events"].lower()
    assert client.get("/reports/security", headers=FRAUD()).status_code == 403


def test_reports_degrade_when_prediction_store_is_down(client, monkeypatch):
    from app.db.base import RepositoryError
    monkeypatch.setattr(client.app.state.repo, "stats", lambda u, d=None: (_ for _ in ()).throw(RepositoryError("down")))
    d = client.get("/reports/overview", headers=FRAUD()).json()
    assert d["fraud"] is None and "unavailable" in d["fraud_error"]
    assert d["cases"]["open"] == 0                                             # the rest still works


# ---------------- admin ----------------
def test_user_admin_requires_admin(client):
    for who in (cust(), FRAUD(), SEC()):
        assert client.get("/admin/users", headers=who).status_code == 403
    assert client.get("/admin/users", headers=admin_h()).status_code == 200


def test_role_change_is_audited_and_logged(local_client):
    tok = local_client.post("/auth/local/login", json={"email": "admin@example.com", "password": "DemoPass!2026"}).json()
    ah = {"Authorization": f"Bearer {tok['access_token']}"}
    users = {u["email"]: u for u in local_client.get("/admin/users", headers=ah).json()["items"]}
    cid = users["customer@example.com"]["id"]
    r = local_client.patch(f"/admin/users/{cid}", json={"role": "fraud_analyst"}, headers=ah)
    assert r.status_code == 200 and r.json()["role"] == "fraud_analyst"
    a = local_client.get("/audit?action=user.updated", headers=ah).json()["items"][0]
    assert a["before"]["role"] == "customer" and a["after"]["role"] == "fraud_analyst" and a["actor_role"] == "admin"
    ev = local_client.get("/security/events?category=privileged", headers=ah).json()
    assert ev["total"] == 1
    # the changed user's NEXT login carries the new role
    t2 = local_client.post("/auth/local/login", json={"email": "customer@example.com", "password": "DemoPass!2026"}).json()
    assert t2["user"]["role"] == "fraud_analyst"


def test_admin_cannot_lock_themselves_out_or_remove_last_admin(local_client):
    tok = local_client.post("/auth/local/login", json={"email": "admin@example.com", "password": "DemoPass!2026"}).json()
    ah = {"Authorization": f"Bearer {tok['access_token']}"}
    me = tok["user"]["id"]
    assert local_client.patch(f"/admin/users/{me}", json={"role": "customer"}, headers=ah).status_code == 409
    assert local_client.patch(f"/admin/users/{me}", json={"is_active": False}, headers=ah).status_code == 409
    assert local_client.patch("/admin/users/nope", json={"role": "customer"}, headers=ah).status_code == 404
    assert local_client.patch(f"/admin/users/{me}", json={}, headers=ah).status_code == 422
    assert local_client.patch(f"/admin/users/{me}", json={"role": "emperor"}, headers=ah).status_code == 422
    # a second admin may demote the first only if one admin remains
    other = {u["email"]: u for u in local_client.get("/admin/users", headers=ah).json()["items"]}["customer@example.com"]["id"]
    local_client.patch(f"/admin/users/{other}", json={"role": "admin"}, headers=ah)
    t2 = local_client.post("/auth/local/login", json={"email": "customer@example.com", "password": "DemoPass!2026"}).json()
    bh = {"Authorization": f"Bearer {t2['access_token']}"}
    assert local_client.patch(f"/admin/users/{me}", json={"is_active": False}, headers=bh).status_code == 200
    assert local_client.patch(f"/admin/users/{other}", json={"role": "customer"}, headers=bh).status_code == 409


def test_audit_trail_is_read_only_and_filterable(client):
    client.patch("/inventory/1", json={"set_available": 9, "reason": "recount"}, headers=admin_h())
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/audit", headers=admin_h()).status_code in (404, 405)
    assert client.get("/audit?actor_id=admin-1", headers=SEC()).json()["total"] == 1
    assert client.get("/audit?action=Bad Action", headers=SEC()).status_code == 422
    assert client.get("/audit?date_from=garbage", headers=SEC()).status_code == 422
    assert client.get("/audit", headers=FRAUD()).status_code == 403
    assert client.get("/audit", headers=cust()).status_code == 403


def test_integrations_status_is_honest_and_leaks_no_secrets(settings):
    settings.safe_browsing_api_key = "SB-KEY-MUST-NOT-LEAK"
    settings.supabase_anon_key = "ANON-KEY-MUST-NOT-LEAK"
    settings.scamwatch_providers = "heuristic,safebrowsing"
    with TestClient(create_app(settings)) as c:
        r = c.get("/settings/integrations", headers=FRAUD())
        d = r.json()
    text = r.text
    for secret in ("SB-KEY-MUST-NOT-LEAK", "ANON-KEY-MUST-NOT-LEAK", settings.supabase_jwt_secret):
        assert secret not in text
    assert d["retailer_connection"]["connected"] is False and "No real retailer" in d["retailer_connection"]["note"]
    assert "SIMULATED" in d["store"]["payment"] and d["authentication"]["supabase_live_tested"] is False
    providers = {p["name"]: p for p in d["scamwatch_providers"]}
    assert providers["safebrowsing"]["configured"] is True and providers["safebrowsing"]["live_tested"] is False
    assert d["payment_model"]["is_synthetic"] is True and d["pca_model"]["available"] is False
    assert d["database"]["application_db"] == "connected"


def test_health_reports_local_auth_flag_and_database(local_client):
    assert local_client.get("/health").json()["local_auth_enabled"] is True
    assert local_client.get("/health").json()["app_database"] == "ok"


# ---------------- migrations / persistence ----------------
def test_migrations_are_idempotent_and_preserve_data(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    assert db.create_all() == [v for v, _, _ in MIGRATIONS]
    from app.db.seed import seed_catalogue
    with db.session() as s:
        seed_catalogue(s, "ZAR")
    assert db.create_all() == [] and migrate(db.engine) == []
    with db.session() as s:
        assert len(s.scalars(select(Product)).all()) == 40
    db.dispose()


def test_data_survives_an_application_restart(settings):
    with TestClient(create_app(settings)) as c1:
        h = cust()
        put_in_cart(c1, h, "DEMO-FP-001", 3)
        oid = c1.post("/orders", json=order_body(), headers=h).json()["id"]
        c1.post("/predict", json=valid_payload(**RISKY), headers=FRAUD())
        before = c1.get("/products?search=DEMO-FP-001").json()["items"][0]["available_quantity"]
    with TestClient(create_app(settings)) as c2:                              # a fresh process-equivalent
        assert c2.get(f"/orders/{oid}", headers=cust()).json()["id"] == oid
        assert c2.get("/products?search=DEMO-FP-001").json()["items"][0]["available_quantity"] == before == 117
        assert c2.get("/investigations", headers=FRAUD()).json()["total"] == 1
        assert c2.get("/transactions", headers=FRAUD()).json()["total"] == 1
        assert c2.get("/products").json()["total"] == 40                      # seeding did not duplicate


# ---------------- model configuration ----------------
def test_model_threshold_override_changes_flagging(settings, model_path):
    p = Predictor(0.7, 0.3, threshold=0.0)
    p.load(model_path)
    assert p.threshold == 0.0 and p.predict(valid_payload() | {"new_device": 0, "international": 0,
                                                                "branch": "Online"}).is_fraud is True
    p2 = Predictor(0.7, 0.3, threshold=1.0)
    p2.load(model_path)
    assert p2.threshold == 1.0 and p2.predict({"amount": 9000.0, "hour": 2, "failed_attempts": 5, "new_device": 1,
                                               "international": 1, "customer_avg_spend": 100.0,
                                               "payment_method": "Card", "branch": "Online"}).is_fraud is False
    p3 = Predictor(0.7, 0.3)
    p3.load(model_path)
    assert p3.threshold == p3.metadata["threshold"]


def test_model_info_reports_effective_threshold_and_bands(settings):
    settings.model_threshold = 0.9
    with TestClient(create_app(settings)) as c:
        d = c.get("/model-info", headers=FRAUD()).json()
        assert d["threshold"] == 0.9 and d["risk_bands"]["high"] == 0.7
        assert c.get("/settings/integrations", headers=FRAUD()).json()["payment_model"]["threshold"] == 0.9
