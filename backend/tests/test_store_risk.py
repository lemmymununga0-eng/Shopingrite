"""store_risk_v1 (rule-based order scoring), the staff order explorer and masking. No machine learning is involved and
none of these tests call the fraud model."""
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditEvent, Case, FraudAssessment
from app.factory import create_app
from app.services import order_risk, store_risk
from app.services.flutterwave import FlutterwaveClient

from .conftest import admin_h, auth, cust, order_body, put_in_cart
from .test_flutterwave import HOOK, KEY, FakeFlutterwave

SKU = "DEMO-FP-001"
FRAUD, SECURITY = auth("fraud-1", "fraud_analyst"), auth("sec-1", "security_analyst")


@pytest.fixture(autouse=True)
def midday(monkeypatch):
    """Make 'local hour' 12 so the night-time rule never depends on when the tests run."""
    monkeypatch.setattr(store_risk, "LOCAL_UTC_OFFSET_HOURS", (12 - datetime.now(timezone.utc).hour) % 24)


def buy(client, h, qty=1, scenario="success", fulfilment="collection", **over):
    put_in_cart(client, h, SKU, qty)
    body = order_body(fulfilment=fulfilment, payment={"method": "simulated", "scenario": scenario}, **over)
    if fulfilment == "collection":
        body.pop("address", None)
    r = client.post("/orders", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def assessments(client, order_id):
    with client.app.state.db.session() as s:
        return [(a.score, a.decision, json.loads(a.reasons_json), a.trigger) for a in
                s.scalars(select(FraudAssessment).where(FraudAssessment.order_id == order_id).order_by(FraudAssessment.id))]


def test_an_ordinary_order_is_scored_allow_and_the_assessment_is_stored(client):
    o = buy(client, cust())
    rows = assessments(client, o["id"])
    assert len(rows) == 1 and rows[0][:3] == (0, "allow", []) and rows[0][3] == "order_placed"
    with client.app.state.db.session() as s:
        assert s.scalar(select(Case).where(Case.source_type == "order_anomaly")) is None     # nothing to investigate


def test_high_value_orders_are_scored_review_and_open_a_case_with_plain_reasons(settings):
    settings.order_high_value_cents = 100
    with TestClient(create_app(settings)) as c:
        o = buy(c, cust())
        score, decision, reasons, _ = assessments(c, o["id"])[0]
        assert [r["rule"] for r in reasons] == ["high_value", "first_order_large"] and score == 45 and decision == "review"
        assert all(r["text"] and r["points"] > 0 for r in reasons)
        d = c.get(f"/staff/orders/{o['id']}", headers=FRAUD).json()
        assert d["assessments"][0]["engine"] == "store_risk_v1" and "not machine learning" in d["assessments"][0]["note"].lower()
        assert d["assessments"][0]["features"]["total_cents"] == o["total_cents"]
        assert d["case"]["case_reference"].startswith("CASE-")
        assert c.get("/investigations?source_type=order_anomaly", headers=FRAUD).json()["total"] == 1


def test_scores_add_up_and_stop_at_100(settings):
    settings.order_high_value_cents, settings.order_bulk_quantity, settings.order_velocity_per_hour = 100, 1, 1
    with TestClient(create_app(settings)) as c:
        o = buy(c, cust(), qty=2)
        score, decision, reasons, _ = assessments(c, o["id"])[0]
        assert {r["rule"] for r in reasons} == {"high_value", "bulk_quantity", "order_velocity", "first_order_large"}
        assert score == sum(r["points"] for r in reasons) == 80 and decision == "high"


def test_repeated_failed_payments_raise_the_score_and_are_reassessed_after_a_payment_fails(settings):
    fake = FakeFlutterwave()
    settings.flw_secret_key, settings.flw_webhook_hash = KEY, HOOK
    with TestClient(create_app(settings, flw=FlutterwaveClient(KEY, transport=httpx.MockTransport(fake.handler)))) as c:
        h = cust()
        put_in_cart(c, h, SKU, 1)
        o = c.post("/orders", json=order_body(fulfilment="collection", payment={"method": "card"}) | {"address": None}, headers=h).json()
        ref = o["payment_attempts"][0]["reference"]
        fake.pay(ref, o["total_cents"] / 100, status="failed")
        assert c.post(f"/payments/{ref}/verify", headers=h).json()["outcome"] == "failed"
        assert len(assessments(c, o["id"])) == 1                       # one failure adds no points: no new noise row
        ref2 = c.post(f"/orders/{o['id']}/pay", json={"method": "card"}, headers=h).json()["payment_attempts"][-1]["reference"]
        fake.pay(ref2, o["total_cents"] / 100, status="failed")
        c.post(f"/payments/{ref2}/verify", headers=h)
        rows = assessments(c, o["id"])
        assert len(rows) == 2 and rows[-1][3] == "payment_failed"
        assert [r["rule"] for r in rows[-1][2]] == ["failed_payments"] and rows[-1][0] == 10


def test_a_new_delivery_address_and_a_spend_spike_are_flagged_but_a_first_order_is_not(settings):
    with TestClient(create_app(settings)) as c:
        h = cust()
        first = buy(c, h, fulfilment="delivery")
        assert assessments(c, first["id"])[0][2] == []                 # the first order has no history to compare against
        second = buy(c, h, fulfilment="delivery", address={"line": "99 Other Road", "city": "Lusaka", "postal_code": "1000"})
        assert [r["rule"] for r in assessments(c, second["id"])[0][2]] == ["new_address"]
        third = buy(c, h, fulfilment="delivery", address={"line": "99 Other Road", "city": "Lusaka", "postal_code": "1000"})
        assert assessments(c, third["id"])[0][2] == []                 # that address is now known
        big = buy(c, h, qty=20)
        rules = [r["rule"] for r in assessments(c, big["id"])[0][2]]
        assert "spend_spike" in rules


def test_night_orders_get_a_small_bump(monkeypatch, client):
    monkeypatch.setattr(store_risk, "LOCAL_UTC_OFFSET_HOURS", (2 - datetime.now(timezone.utc).hour) % 24)
    o = buy(client, cust())
    assert [(r["rule"], r["points"]) for r in assessments(client, o["id"])[0][2]] == [("night_order", 5)]


def test_re_evaluating_an_unchanged_order_adds_nothing(client):
    o = buy(client, cust())
    app = client.app
    order_risk.evaluate(app.state.db, app.state.events, app.state.settings, o["id"])
    order_risk.evaluate(app.state.db, app.state.events, app.state.settings, o["id"], trigger="payment_failed")
    assert len(assessments(client, o["id"])) == 1


# ------------------------------------------------------------------------------------------------- staff explorer
def test_staff_explorer_lists_orders_with_risk_and_filters(settings):
    settings.order_high_value_cents = 100
    with TestClient(create_app(settings)) as c:
        risky = buy(c, cust("cust-1"))
        settings.order_high_value_cents = 10_000_000
        calm = buy(c, cust("cust-2"))
        everything = c.get("/staff/orders", headers=FRAUD).json()
        assert everything["total"] == 2
        by_ref = {i["reference"]: i for i in everything["items"]}
        assert by_ref[risky["reference"]]["risk"]["decision"] == "review" and by_ref[calm["reference"]]["risk"]["decision"] == "allow"
        assert by_ref[risky["reference"]]["case"]["status"] == "new"
        only = c.get("/staff/orders?decision=review", headers=FRAUD).json()
        assert [i["reference"] for i in only["items"]] == [risky["reference"]]
        assert c.get("/staff/orders?payment_status=paid", headers=FRAUD).json()["total"] == 2
        assert c.get(f"/staff/orders?search={calm['reference'][:8]}", headers=FRAUD).json()["total"] == 1
        assert c.get("/staff/orders?decision=bogus", headers=FRAUD).status_code == 422
        summary = c.get("/staff/risk-summary", headers=SECURITY).json()
        assert summary["counts"] == {"allow": 1, "review": 1, "high": 0} and "machine learning" in summary["note"]


def test_staff_orders_are_not_available_to_customers_or_anonymous(client):
    o = buy(client, cust())
    for path in ("/staff/orders", f"/staff/orders/{o['id']}", "/staff/risk-summary"):
        assert client.get(path, headers=cust()).status_code == 403
        assert client.get(path).status_code == 401


def test_analysts_see_masked_contact_details_and_admins_see_all_with_an_audit_record(client):
    o = buy(client, cust(), fulfilment="delivery")
    a = client.get(f"/staff/orders/{o['id']}", headers=FRAUD).json()
    assert a["contact_masked"] is True
    assert a["order"]["contact_phone"] == "+26097****567" and a["order"]["contact_email"] == "s***@example.com"
    assert a["order"]["address_line"] == "(hidden)"
    assert "0971234567" not in json.dumps(a) and "12 Test Street" not in json.dumps(a)
    full = client.get(f"/staff/orders/{o['id']}", headers=admin_h()).json()
    assert full["contact_masked"] is False and full["order"]["contact_phone"] == "+260971234567"
    assert full["order"]["address_line"] == "12 Test Street"
    with client.app.state.db.session() as s:
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "order.contact_viewed")) is not None
    assert [h["to"] for h in full["history"]] == ["awaiting_payment", "confirmed"]


def test_staff_order_detail_handles_bad_ids(client):
    assert client.get("/staff/orders/not-a-uuid", headers=FRAUD).status_code == 404
    assert client.get("/staff/orders/00000000-0000-0000-0000-000000000000", headers=FRAUD).status_code == 404


def test_mask_helpers():
    from app.routers.staff_orders import mask_email, mask_phone
    assert mask_phone("+260971234567") == "+26097****567" and mask_phone("12") == "****"
    assert mask_email("jane.doe@example.com") == "j***@example.com" and mask_email("nope") == "***"
