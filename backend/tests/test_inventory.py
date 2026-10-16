"""Staff inventory view and audited administrator stock adjustments."""
import json

from sqlalchemy import select

from app.db.models import AuditEvent, SecurityEvent

from .conftest import admin_h, auth, cust, pid


def test_inventory_visible_to_staff_only(client):
    assert client.get("/inventory").status_code == 401
    assert client.get("/inventory", headers=cust()).status_code == 403
    for role in ("fraud_analyst", "security_analyst", "admin"):
        r = client.get("/inventory", headers=auth("x", role))
        assert r.status_code == 200 and r.json()["total"] == 40


def test_inventory_filters(client):
    h = admin_h()
    low = client.get("/inventory?status=low_stock&page_size=100", headers=h).json()
    assert low["total"] > 0 and all(0 < i["available_quantity"] <= i["reorder_threshold"] for i in low["items"])
    out = client.get("/inventory?status=out_of_stock&page_size=100", headers=h).json()
    assert out["total"] == 4 and all(i["available_quantity"] == 0 for i in out["items"])
    assert client.get("/inventory?status=bogus", headers=h).status_code == 422
    assert client.get("/inventory?search=milk", headers=h).json()["total"] == 1


def test_only_admin_can_adjust_stock(client):
    p = pid(client, "DEMO-FP-001")
    body = {"set_available": 10, "reason": "recount"}
    assert client.patch(f"/inventory/{p}", json=body).status_code == 401
    for who in (cust(), auth("f", "fraud_analyst"), auth("s", "security_analyst")):
        assert client.patch(f"/inventory/{p}", json=body, headers=who).status_code == 403
    r = client.patch(f"/inventory/{p}", json=body, headers=admin_h())
    assert r.status_code == 200 and r.json()["available_quantity"] == 10


def test_adjustment_is_audited_with_reason_and_logged_as_event(client):
    p = pid(client, "DEMO-FP-001")
    client.patch(f"/inventory/{p}", json={"delta": -20, "reason": "damaged in storage"}, headers=admin_h())
    with client.app.state.db.session() as s:
        a = s.scalar(select(AuditEvent).where(AuditEvent.action == "inventory.adjusted"))
        assert a.actor_id == "admin-1" and a.actor_role == "admin" and a.entity_id == str(p)
        assert json.loads(a.before_json)["available_quantity"] == 120
        after = json.loads(a.after_json)
        assert after["available_quantity"] == 100 and after["reason"] == "damaged in storage"
        assert s.scalar(select(SecurityEvent).where(SecurityEvent.event_type == "inventory.adjusted")) is not None


def test_invalid_adjustments(client):
    p, h = pid(client, "DEMO-FP-001"), admin_h()
    assert client.patch(f"/inventory/{p}", json={"delta": -9999, "reason": "too much"}, headers=h).status_code == 422
    assert client.patch(f"/inventory/{p}", json={"set_available": -1, "reason": "negative"}, headers=h).status_code == 422
    assert client.patch(f"/inventory/{p}", json={"set_available": 1, "delta": 1, "reason": "both"}, headers=h).status_code == 422
    assert client.patch(f"/inventory/{p}", json={"set_available": 5}, headers=h).status_code == 422            # reason required
    assert client.patch(f"/inventory/{p}", json={"set_available": 5, "reason": "x" * 3, "extra": 1}, headers=h).status_code == 422
    assert client.patch("/inventory/99999", json={"set_available": 5, "reason": "missing"}, headers=h).status_code == 404
