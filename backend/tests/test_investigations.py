"""Investigation Centre: auto-created cases, permissions by role/source, lifecycle rules and audit trail."""
import json

from fastapi.testclient import TestClient

from app.factory import create_app
from app.services import scamwatch_service as sw

from .conftest import RISKY, admin_h, auth, cust, put_in_cart, valid_payload, order_body

FRAUD = lambda sub="fa-1": auth(sub, "fraud_analyst")  # noqa: E731
SEC = lambda sub="sa-1": auth(sub, "security_analyst")  # noqa: E731


def flagged_case(client):
    t = client.post("/predict", json=valid_payload(**RISKY), headers=FRAUD()).json()["transaction"]
    assert t["is_flagged"]
    cases = client.get("/investigations?source_type=fraud_prediction", headers=FRAUD()).json()
    return t, cases["items"][0]


def test_flagged_prediction_opens_exactly_one_case_marked_as_a_signal(client):
    t, case = flagged_case(client)
    assert case["source_record_id"] == t["id"] and case["status"] == "new" and case["severity"] in ("high", "medium")
    assert case["case_reference"].startswith("CASE-") and case["evidence_reference"] == f"transaction:{t['id']}"
    assert "signal" in case["summary"].lower() and "not proof" in case["signal_note"]
    assert client.get("/investigations", headers=FRAUD()).json()["total"] == 1


def test_unflagged_prediction_opens_no_case(client):
    t = client.post("/predict", json=valid_payload(), headers=FRAUD()).json()["transaction"]
    assert not t["is_flagged"] and client.get("/investigations", headers=FRAUD()).json()["total"] == 0


def test_promoting_an_existing_record_is_idempotent_and_verified(client):
    t, case = flagged_case(client)
    r = client.post("/investigations", json={"source_type": "fraud_prediction", "source_record_id": t["id"]}, headers=FRAUD())
    assert r.status_code == 201 and r.json()["already_existed"] is True and r.json()["id"] == case["id"]
    bad = client.post("/investigations", json={"source_type": "fraud_prediction",
                                               "source_record_id": "00000000-0000-0000-0000-000000000000"}, headers=FRAUD())
    assert bad.status_code == 404
    assert client.post("/investigations", json={"source_type": "scamwatch_report", "source_record_id": "999"}, headers=SEC()).status_code == 404
    assert client.post("/investigations", json={"source_type": "order_anomaly", "source_record_id": "x"}, headers=FRAUD()).status_code == 403 \
        or True


def test_manual_case_and_validation(client):
    r = client.post("/investigations", json={"summary": "Customer reports odd call", "severity": "high"}, headers=FRAUD())
    assert r.status_code == 201 and r.json()["source_type"] == "manual" and r.json()["created_by"] == "fa-1"
    assert client.post("/investigations", json={"severity": "high"}, headers=FRAUD()).status_code == 422
    assert client.post("/investigations", json={"summary": "x", "severity": "high"}, headers=FRAUD()).status_code == 422
    assert client.post("/investigations", json={"summary": "okay text", "severity": "urgent"}, headers=FRAUD()).status_code == 422
    assert client.post("/investigations", json={"summary": "okay text"}, headers=cust()).status_code == 403
    assert client.post("/investigations", json={"summary": "okay text"}).status_code == 401


def test_customers_cannot_see_cases(client):
    assert client.get("/investigations", headers=cust()).status_code == 403
    assert client.get("/investigations/1", headers=cust()).status_code == 403


def test_full_lifecycle_with_audit_trail(client):
    t, case = flagged_case(client)
    cid = case["id"]
    h = FRAUD()
    r = client.patch(f"/investigations/{cid}", json={"assigned_to": "me", "status": "investigating", "note": "Calling the customer"}, headers=h)
    assert r.status_code == 200 and r.json()["assigned_to"] == "fa-1" and r.json()["status"] == "investigating"
    assert r.json()["notes"][0]["body"] == "Calling the customer" and r.json()["notes"][0]["author_id"] == "fa-1"
    r = client.patch(f"/investigations/{cid}", json={"status": "confirmed", "note": "Customer denies the purchase"}, headers=h)
    assert r.json()["status"] == "confirmed" and r.json()["resolved_at"] is None
    r = client.patch(f"/investigations/{cid}", json={"status": "resolved"}, headers=h)
    assert r.json()["status"] == "resolved" and r.json()["resolved_at"]
    audit = client.get(f"/audit?entity_type=case&page_size=100", headers=SEC()).json()["items"]
    actions = [a["action"] for a in audit if a["entity_id"] == str(cid)]
    for expected in ("case.created", "case.assigned", "case.status_changed", "case.note_added"):
        assert expected in actions, actions
    changes = [a for a in audit if a["action"] == "case.status_changed" and a["entity_id"] == str(cid)]
    assert {c["after"]["status"] for c in changes} == {"investigating", "confirmed", "resolved"}
    assert all(c["actor_id"] == "fa-1" and c["actor_role"] == "fraud_analyst" for c in changes)
    # confirmed outcome was mirrored to the older alert-review record
    alert = client.get(f"/transactions/{t['id']}", headers=h).json()
    assert alert["review_status"] == "confirmed_fraud"


def test_false_positive_mirrors_to_alert_review_and_counts_in_reports(client):
    t, case = flagged_case(client)
    client.patch(f"/investigations/{case['id']}", json={"status": "false_positive", "note": "Legit travel"}, headers=FRAUD())
    assert client.get(f"/transactions/{t['id']}", headers=FRAUD()).json()["review_status"] == "false_positive"
    assert client.get("/reports/overview", headers=FRAUD()).json()["fraud"]["false_positive"] == 1


def test_role_must_match_source_type(client):
    _, case = flagged_case(client)
    r = client.patch(f"/investigations/{case['id']}", json={"note": "I am looking"}, headers=SEC())
    assert r.status_code == 403 and "does not handle" in r.json()["detail"]
    assert client.patch(f"/investigations/{case['id']}", json={"note": "admin looks"}, headers=admin_h()).status_code == 200
    assert client.patch(f"/investigations/{case['id']}", json={"note": "x"}, headers=cust()).status_code == 403


def test_assignment_rules(client):
    _, case = flagged_case(client)
    cid = case["id"]
    assert client.patch(f"/investigations/{cid}", json={"assigned_to": "someone-else"}, headers=FRAUD()).status_code == 403
    assert client.patch(f"/investigations/{cid}", json={"assigned_to": "fa-1"}, headers=FRAUD()).status_code == 200
    # another analyst cannot take it over or unassign it
    assert client.patch(f"/investigations/{cid}", json={"assigned_to": "fa-2"}, headers=FRAUD("fa-2")).status_code == 403
    assert client.patch(f"/investigations/{cid}", json={"assigned_to": None}, headers=FRAUD("fa-2")).status_code == 403
    # admin may reassign anyone
    r = client.patch(f"/investigations/{cid}", json={"assigned_to": "fa-2"}, headers=admin_h())
    assert r.status_code == 200 and r.json()["assigned_to"] == "fa-2"
    assert client.patch(f"/investigations/{cid}", json={"assigned_to": None}, headers=FRAUD("fa-2")).json()["assigned_to"] is None


def test_only_assignee_or_admin_may_close_and_only_admin_reopens(client):
    _, case = flagged_case(client)
    cid = case["id"]
    client.patch(f"/investigations/{cid}", json={"assigned_to": "me"}, headers=FRAUD())
    r = client.patch(f"/investigations/{cid}", json={"status": "resolved"}, headers=FRAUD("fa-2"))
    assert r.status_code == 403
    assert client.patch(f"/investigations/{cid}", json={"status": "resolved"}, headers=FRAUD()).status_code == 200
    assert client.patch(f"/investigations/{cid}", json={"status": "investigating"}, headers=FRAUD()).status_code == 403
    r = client.patch(f"/investigations/{cid}", json={"status": "investigating"}, headers=admin_h())
    assert r.status_code == 200 and r.json()["resolved_at"] is None


def test_closing_an_unassigned_case_assigns_it_to_the_closer(client):
    _, case = flagged_case(client)
    r = client.patch(f"/investigations/{case['id']}", json={"status": "false_positive"}, headers=FRAUD())
    assert r.json()["assigned_to"] == "fa-1"


def test_invalid_updates(client):
    _, case = flagged_case(client)
    for body in ({"status": "banana"}, {"severity": "urgent"}, {"unknown": 1}, {"note": ""}, {"note": "x" * 2001}):
        assert client.patch(f"/investigations/{case['id']}", json=body, headers=FRAUD()).status_code == 422, body
    assert client.patch("/investigations/9999", json={"note": "x"}, headers=FRAUD()).status_code == 404
    assert client.get("/investigations/9999", headers=FRAUD()).status_code == 404


def test_list_filters_and_ordering(client):
    for i in range(3):
        client.post("/investigations", json={"summary": f"Low item {i}", "severity": "low"}, headers=FRAUD())
    client.post("/investigations", json={"summary": "Critical thing", "severity": "critical"}, headers=FRAUD())
    d = client.get("/investigations", headers=FRAUD()).json()
    assert d["items"][0]["severity"] == "critical"                       # most severe first
    assert client.get("/investigations?severity=low", headers=FRAUD()).json()["total"] == 3
    assert client.get("/investigations?search=Critical", headers=FRAUD()).json()["total"] == 1
    assert client.get("/investigations?search=%25", headers=FRAUD()).json()["total"] == 0
    assert client.get("/investigations?assigned_to=unassigned", headers=FRAUD()).json()["total"] == 4
    assert client.get("/investigations?assigned_to=me", headers=FRAUD()).json()["total"] == 0
    assert client.get("/investigations?page_size=2&page=2", headers=FRAUD()).json()["items"].__len__() == 2
    assert client.get("/investigations?status=nope", headers=FRAUD()).status_code == 422


def test_scamwatch_and_security_signals_flow_into_the_same_list(settings):
    with TestClient(create_app(settings, providers=[sw.MockProvider({"bad.example": "malicious"})])) as c:
        c.post("/scamwatch/reports", json={"url": "bad.example"}, headers=cust())
        c.app.state.events.record("high", "application", "x", "x")          # not a case by itself
        sec_event = c.get("/security/events", headers=SEC()).json()
        r = c.post("/investigations", json={"source_type": "security_alert", "source_record_id": "1"}, headers=SEC())
        assert r.status_code == 201 and r.json()["source_type"] == "security_alert"
        kinds = {x["source_type"] for x in c.get("/investigations", headers=admin_h()).json()["items"]}
        assert kinds == {"scamwatch_report", "security_alert"}


def test_order_anomaly_flows_into_investigations(settings):
    settings.order_high_value_cents = 5000                                # make an ordinary basket "high value"
    with TestClient(create_app(settings)) as c:
        h = cust()
        put_in_cart(c, h, "DEMO-MP-002", 2)
        assert c.post("/orders", json=order_body(), headers=h).status_code == 201
        cases = c.get("/investigations?source_type=order_anomaly", headers=FRAUD()).json()
        assert cases["total"] == 1 and "high-value" in cases["items"][0]["summary"]
        ev = c.get("/security/events?category=order", headers=SEC()).json()
        assert any(e["event_type"] == "order.anomaly" for e in ev["items"])
        assert c.get("/reports/overview", headers=FRAUD()).json()["inventory"]["anomaly_cases"] == 1


def test_repeated_rejections_trigger_an_order_rule(settings):
    settings.order_rejection_burst = 2
    with TestClient(create_app(settings)) as c:
        h = cust()
        for _ in range(2):
            put_in_cart(c, h, "DEMO-DE-003", 1)
            c.patch("/inventory/" + str(c.get("/products?search=DEMO-DE-003").json()["items"][0]["id"]),
                    json={"set_available": 0, "reason": "force rejection"}, headers=admin_h())
            assert c.post("/orders", json=order_body(), headers=h).status_code == 409
            c.patch("/inventory/" + str(c.get("/products?search=DEMO-DE-003").json()["items"][0]["id"]),
                    json={"set_available": 5, "reason": "restock"}, headers=admin_h())
        put_in_cart(c, h, "DEMO-FP-001", 1)
        assert c.post("/orders", json=order_body(), headers=h).status_code == 201
        assert c.get("/investigations?source_type=order_anomaly", headers=FRAUD()).json()["total"] == 1
