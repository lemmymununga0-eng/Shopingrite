"""Payment attempts, order states, idempotency, stock holds/expiry, the stock ledger, webhooks, Zambian phone numbers,
and the orders-table migration. Everything here uses the SIMULATED provider: no real payment exists."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app.db.models import AuditEvent, Order, OrderStatusHistory, PaymentAttempt, PaymentEvent, StockMovement, utcnow
from app.factory import create_app
from app.services import payment_service as pay
from app.services.stock_ledger import mismatches

from .conftest import admin_h, cust, order_body, put_in_cart, stock

SKU = "DEMO-FP-001"


def go(client, h, scenario="success", method="simulated", key=None, qty=2, **over):
    put_in_cart(client, h, SKU, qty)
    headers = dict(h)
    if key:
        headers["Idempotency-Key"] = key
    return client.post("/orders", json=order_body(payment={"method": method, "scenario": scenario}, **over), headers=headers)


def ledger_ok(client):
    with client.app.state.db.session() as s:
        return mismatches(s)


def test_success_confirms_and_marks_paid(client):
    h = cust()
    r = go(client, h, "success")
    o = r.json()
    assert r.status_code == 201 and o["status"] == "confirmed" and o["payment_status"] == "paid"
    a = o["payment_attempts"][0]
    assert a["status"] == "succeeded" and a["reference"].startswith("PAY-") and a["mode"] == "SIMULATED"
    assert "no money" in o["payment_notice"].lower() and o["payment_due_at"] is None
    assert ledger_ok(client) == []


def test_failure_keeps_order_unpaid_and_never_becomes_paid(client):
    h = cust()
    o = go(client, h, "failure").json()
    assert o["status"] == "payment_failed" and o["payment_status"] == "failed"
    assert o["payment_attempts"][0]["status"] == "failed" and o["payment_attempts"][0]["failure_reason"]
    assert stock(client, SKU) == 118                      # held for a retry until the payment window ends
    assert client.get(f"/orders/{o['id']}", headers=h).json()["payment_status"] == "failed"


def test_retry_after_failure_creates_a_second_attempt_and_can_succeed(client):
    h = cust()
    o = go(client, h, "failure").json()
    r = client.post(f"/orders/{o['id']}/pay", json={"method": "simulated", "scenario": "success"}, headers=h)
    d = r.json()
    assert r.status_code == 200 and d["status"] == "confirmed" and d["payment_status"] == "paid"
    assert [a["status"] for a in d["payment_attempts"]] == ["failed", "succeeded"]
    assert len({a["reference"] for a in d["payment_attempts"]}) == 2
    assert ledger_ok(client) == []


def test_pending_then_customer_resolves_it(client):
    h = cust()
    o = go(client, h, "pending").json()
    assert o["status"] == "awaiting_payment" and o["payment_status"] == "pending"      # pending is never shown as paid
    ref = o["payment_attempts"][0]["reference"]
    assert client.post(f"/orders/{o['id']}/pay", json={"method": "simulated"}, headers=h).status_code == 409   # one at a time
    r = client.post(f"/payments/{ref}/simulate", json={"outcome": "succeeded"}, headers=h)
    assert r.status_code == 200 and r.json()["order"]["status"] == "confirmed"
    assert client.post(f"/payments/{ref}/simulate", json={"outcome": "failed"}, headers=h).status_code == 409
    assert client.get(f"/orders/{o['id']}", headers=h).json()["payment_status"] == "paid"   # a finished payment never flips


def test_cancelled_payment_and_action_required_states(client):
    h = cust()
    c = go(client, h, "cancelled").json()
    assert c["status"] == "payment_failed" and c["payment_status"] == "cancelled"
    a = go(client, cust("cust-2"), "action_required").json()
    assert a["status"] == "awaiting_payment" and a["payment_status"] == "requires_action"
    assert a["payment_attempts"][0]["status"] == "requires_action"


def test_cancelling_an_unpaid_order_restocks_and_is_audited(client):
    h = cust()
    o = go(client, h, "pending").json()
    assert stock(client, SKU) == 118
    r = client.post(f"/orders/{o['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["payment_status"] == "cancelled"
    assert stock(client, SKU) == 120
    assert ledger_ok(client) == []
    with client.app.state.db.session() as s:
        hist = [(x.from_status, x.to_status) for x in s.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == o["id"]).order_by(OrderStatusHistory.id))]
    assert hist == [("", "awaiting_payment"), ("awaiting_payment", "cancelled")]


def test_other_customers_cannot_see_pay_or_resolve(client):
    owner, other = cust("cust-1"), cust("cust-2")
    o = go(client, owner, "pending").json()
    ref = o["payment_attempts"][0]["reference"]
    assert client.get(f"/payments/{ref}", headers=other).status_code == 404
    assert client.post(f"/payments/{ref}/simulate", json={"outcome": "succeeded"}, headers=other).status_code == 404
    assert client.post(f"/orders/{o['id']}/pay", json={"method": "simulated"}, headers=other).status_code == 404
    assert client.get(f"/payments/{ref}", headers=owner).status_code == 200
    assert client.get("/payments/not-a-reference", headers=owner).status_code == 404


def test_unavailable_methods_are_listed_honestly(client):
    ms = {m["id"]: m for m in client.get("/payments/methods").json()["methods"]}
    assert ms["simulated"]["available"] and ms["simulated"]["mode"] == "SIMULATED"
    assert ms["cod"]["available"] is False
    for k in ("airtel_money", "mtn_momo", "card"):
        assert ms[k]["available"] is False and "not available" in ms[k]["reason"].lower()


def test_cash_on_delivery_only_when_enabled(settings):
    with TestClient(create_app(settings)) as c:
        h = cust()
        r = go(c, h, method="cod")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "cod_disabled"
        assert stock(c, SKU) == 120
    settings.cod_enabled = True
    with TestClient(create_app(settings)) as c:
        o = go(c, cust(), method="cod").json()
        assert o["status"] == "confirmed" and o["payment_status"] == "cod_due" and o["payment_mode"] == "COD"
        assert o["payment_attempts"][0]["status"] == "pending"          # nothing is paid until the courier collects


# ---------------------------------------------------------------- idempotency
def test_same_idempotency_key_returns_the_same_order(client):
    h = cust()
    put_in_cart(client, h, SKU, 2)
    key = "checkout-key-0001"
    r1 = client.post("/orders", json=order_body(), headers={**h, "Idempotency-Key": key})
    r2 = client.post("/orders", json=order_body(), headers={**h, "Idempotency-Key": key})
    assert r1.status_code == 201 and r2.status_code == 200 and r2.headers["Idempotent-Replay"] == "true"
    assert r1.json()["id"] == r2.json()["id"] and r1.json()["payment_attempts"][0]["reference"] == r2.json()["payment_attempts"][0]["reference"]
    assert client.get("/orders", headers=h).json()["total"] == 1 and stock(client, SKU) == 118


def test_idempotency_key_with_a_different_request_is_refused(client):
    h = cust()
    put_in_cart(client, h, SKU, 2)
    key = "checkout-key-0002"
    assert client.post("/orders", json=order_body(), headers={**h, "Idempotency-Key": key}).status_code == 201
    r = client.post("/orders", json=order_body(fulfilment="collection"), headers={**h, "Idempotency-Key": key})
    assert r.status_code == 422


def test_idempotency_keys_are_per_customer(client):
    key = "shared-key-123456"
    a = go(client, cust("cust-1"), key=key).json()
    b = go(client, cust("cust-2"), key=key).json()
    assert a["id"] != b["id"]


def test_a_rejected_checkout_does_not_burn_the_key(client):
    h = cust()
    key = "retry-key-0000001"
    r = client.post("/orders", json=order_body(), headers={**h, "Idempotency-Key": key})
    assert r.status_code == 409                                         # empty cart
    assert go(client, h, key=key).status_code == 201


# ---------------------------------------------------------------- hold, expiry, ledger
def _expire(client, order_id):
    with client.app.state.db.session() as s:
        s.get(Order, order_id).payment_due_at = utcnow() - timedelta(minutes=1)


def test_unpaid_order_expires_and_stock_returns(client):
    h = cust()
    o = go(client, h, "pending", qty=5).json()
    assert stock(client, SKU) == 115 and o["payment_due_at"]
    _expire(client, o["id"])
    d = client.get(f"/orders/{o['id']}", headers=h).json()
    assert d["status"] == "cancelled" and d["payment_status"] == "cancelled"
    assert d["payment_attempts"][0]["status"] == "cancelled"
    assert stock(client, SKU) == 120 and ledger_ok(client) == []
    assert client.post(f"/orders/{o['id']}/pay", json={"method": "simulated"}, headers=h).status_code == 409
    with client.app.state.db.session() as s:
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "order.payment_expired")) is not None
        reasons = [m.reason for m in s.scalars(select(StockMovement).where(StockMovement.order_id == o["id"]))]
    assert reasons == ["order_reserved", "order_expired"]


def test_expiry_never_touches_paid_orders(client):
    h = cust()
    o = go(client, h, "success").json()
    with client.app.state.db.session() as s:
        s.get(Order, o["id"]).payment_due_at = utcnow() - timedelta(hours=1)
    assert client.get(f"/orders/{o['id']}", headers=h).json()["status"] == "confirmed"


def test_expired_hold_frees_the_last_unit_for_another_shopper(client):
    a, b = cust("cust-1"), cust("cust-2")
    with client.app.state.db.session() as s:
        from app.db.models import Inventory, Product
        pid_ = s.scalar(select(Product.id).where(Product.sku == SKU))
        inv = s.get(Inventory, pid_)
        s.add(StockMovement(product_id=pid_, delta_available=1 - inv.available_quantity, reason="admin_adjustment", note="test"))
        inv.available_quantity = 1
    first = go(client, a, "pending", qty=1).json()
    assert put_in_cart(client, b, SKU, 1).status_code == 409             # the only unit is held by the first shopper
    _expire(client, first["id"])
    assert put_in_cart(client, b, SKU, 1).status_code == 201             # hold ended: the unit is on sale again
    assert client.post("/orders", json=order_body(), headers=b).status_code == 201


def test_ledger_matches_inventory_through_reserve_cancel_complete_and_admin_adjustment(client):
    h = cust()
    o1 = go(client, h, "success", qty=3).json()
    o2 = go(client, h, "pending", qty=2).json()
    client.post(f"/orders/{o2['id']}/cancel", headers=h)
    for st in ("picking", "ready", "completed"):
        assert client.patch(f"/orders/{o1['id']}/status", json={"status": st}, headers=admin_h()).status_code == 200
    pidv = client.get(f"/products?search={SKU}").json()["items"][0]["id"]
    assert client.patch(f"/inventory/{pidv}", json={"delta": 7, "reason": "delivery received"}, headers=admin_h()).status_code == 200
    assert ledger_ok(client) == []
    with client.app.state.db.session() as s:
        reasons = [m.reason for m in s.scalars(select(StockMovement).where(StockMovement.product_id == pidv).order_by(StockMovement.id))]
    assert reasons == ["initial_stock", "order_reserved", "order_reserved", "order_cancelled", "order_completed", "admin_adjustment"]


def test_admin_cannot_mark_an_unpaid_order_confirmed(client):
    h = cust()
    o = go(client, h, "pending").json()
    r = client.patch(f"/orders/{o['id']}/status", json={"status": "picking"}, headers=admin_h())
    assert r.status_code == 409


# ---------------------------------------------------------------- webhooks
SECRET = "webhook-secret-for-tests-0123456789"


def _hook(client, body, secret=SECRET, sig=None):
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    s = sig if sig is not None else (pay.sign(secret, raw) if secret else None)
    if s:
        headers["X-Signature"] = s
    return client.post("/payments/webhooks/simulated", content=raw, headers=headers)


@pytest.fixture()
def hclient(settings):
    settings.payment_webhook_secret = SECRET
    with TestClient(create_app(settings)) as c:
        yield c


def test_webhook_applies_a_signed_event_once(hclient):
    h = cust()
    o = go(hclient, h, "pending").json()
    ref = o["payment_attempts"][0]["reference"]
    ev = {"event_id": "evt-000001", "payment_reference": ref, "outcome": "succeeded"}
    r = _hook(hclient, ev)
    assert r.status_code == 200 and r.json()["applied"] is True
    assert hclient.get(f"/orders/{o['id']}", headers=h).json()["status"] == "confirmed"
    again = _hook(hclient, ev)
    assert again.status_code == 200 and again.json() == {"status": "duplicate", "applied": False}
    with hclient.app.state.db.session() as s:
        assert len(s.scalars(select(PaymentEvent)).all()) == 1


def test_webhook_cannot_flip_a_finished_payment(hclient):
    h = cust()
    o = go(hclient, h, "success").json()
    ref = o["payment_attempts"][0]["reference"]
    r = _hook(hclient, {"event_id": "evt-000002", "payment_reference": ref, "outcome": "failed"})
    assert r.status_code == 200 and r.json()["applied"] is False
    assert hclient.get(f"/orders/{o['id']}", headers=h).json()["payment_status"] == "paid"


def test_webhook_rejects_bad_missing_or_disabled_signatures(client, hclient):
    h = cust()
    ref = go(hclient, h, "pending").json()["payment_attempts"][0]["reference"]
    ev = {"event_id": "evt-000003", "payment_reference": ref, "outcome": "succeeded"}
    assert _hook(hclient, ev, sig="0" * 64).status_code == 401
    assert _hook(hclient, ev, secret=None).status_code == 401
    assert _hook(hclient, ev, secret="wrong-secret-wrong-secret-12345").status_code == 401
    raw = json.dumps(ev).encode()
    assert client.post("/payments/webhooks/simulated", content=raw, headers={"X-Signature": pay.sign("", raw)}).status_code == 401
    with hclient.app.state.db.session() as s:
        assert s.scalar(select(PaymentAttempt.status).where(PaymentAttempt.reference == ref)) == "pending"


def test_webhook_unknown_reference_and_bad_body(hclient):
    assert _hook(hclient, {"event_id": "evt-000004", "payment_reference": "PAY-00000000", "outcome": "succeeded"}).status_code == 404
    assert _hook(hclient, {"nonsense": True}).status_code == 422


def test_late_success_after_expiry_is_ignored(hclient):
    h = cust()
    o = go(hclient, h, "pending").json()
    ref = o["payment_attempts"][0]["reference"]
    _expire(hclient, o["id"])
    hclient.get(f"/orders/{o['id']}", headers=h)                                           # sweep
    r = _hook(hclient, {"event_id": "evt-000005", "payment_reference": ref, "outcome": "succeeded"})
    assert r.json()["applied"] is False
    assert hclient.get(f"/orders/{o['id']}", headers=h).json()["status"] == "cancelled"


# ---------------------------------------------------------------- input rules
@pytest.mark.parametrize("phone,expected", [("0971234567", "+260971234567"), ("+260 97 123 4567", "+260971234567"),
                                            ("260771234567", "+260771234567"), ("(0211) 234-567", "+260211234567")])
def test_zambian_phone_numbers_are_validated_and_normalised(client, phone, expected):
    h = cust()
    put_in_cart(client, h, SKU, 1)
    body = order_body()
    body["contact"] = {**body["contact"], "phone": phone}
    r = client.post("/orders", json=body, headers=h)
    assert r.status_code == 201 and r.json()["contact_phone"] == expected


@pytest.mark.parametrize("phone", ["0821234567", "12345", "+27821234567", "097123456", "abcdefghij"])
def test_non_zambian_phone_numbers_are_rejected(client, phone):
    body = order_body()
    body["contact"] = {**body["contact"], "phone": phone}
    assert client.post("/orders", json=body, headers=cust()).status_code == 422


def test_area_and_delivery_instructions_are_stored_and_postal_code_is_optional(client):
    h = cust()
    put_in_cart(client, h, SKU, 1)
    body = order_body(area="Kabulonga", delivery_instructions="Blue gate, call on arrival")
    body["address"] = {"line": "12 Test Street", "city": "Lusaka"}
    o = client.post("/orders", json=body, headers=h).json()
    assert o["area"] == "Kabulonga" and o["delivery_instructions"] == "Blue gate, call on arrival" and o["postal_code"] == ""


# ---------------------------------------------------------------- migration 3
def test_migration_3_rebuilds_orders_without_losing_items_or_stock(tmp_path, monkeypatch):
    from app.db import migrations as m
    eng = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, sku VARCHAR(40))"))
        c.execute(text("CREATE TABLE inventory (product_id INTEGER PRIMARY KEY REFERENCES products(id), available_quantity INTEGER, "
                       "reserved_quantity INTEGER, reorder_threshold INTEGER, updated_at DATETIME)"))
        c.execute(text(
            "CREATE TABLE orders (id VARCHAR(36) PRIMARY KEY, reference VARCHAR(24) UNIQUE, user_id VARCHAR(64), status VARCHAR(24), "
            "fulfilment VARCHAR(12), contact_name VARCHAR(120), contact_email VARCHAR(254), contact_phone VARCHAR(30), "
            "address_line VARCHAR(200), city VARCHAR(80), postal_code VARCHAR(12), subtotal_cents INTEGER, delivery_fee_cents INTEGER, "
            "total_cents INTEGER, currency VARCHAR(3), payment_mode VARCHAR(12), payment_status VARCHAR(24), created_at DATETIME, "
            "updated_at DATETIME, CONSTRAINT ck_order_status CHECK (status in ('confirmed','picking','ready','out_for_delivery','completed','cancelled')))"))
        c.execute(text("CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id VARCHAR(36) NOT NULL REFERENCES orders(id) ON DELETE CASCADE, "
                       "product_id INTEGER, sku VARCHAR(40), name_snapshot VARCHAR(160), unit_price_cents INTEGER, quantity INTEGER, line_total_cents INTEGER)"))
        c.execute(text("INSERT INTO products VALUES (1,'A')"))
        c.execute(text("INSERT INTO inventory VALUES (1, 90, 10, 5, CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO orders VALUES ('o1','ORD-1','u','confirmed','delivery','N','e@x.co','0971234567','l','Lusaka','',1000,0,1000,'ZMW',"
                       "'SIMULATED','simulated_approved',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO order_items VALUES (1,'o1',1,'A','Thing',500,2,1000)"))
    monkeypatch.setattr(m, "MIGRATIONS", [x for x in m.MIGRATIONS if x[0] == 3])
    assert m.migrate(eng) == [3]
    assert m.migrate(eng) == []
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM order_items")).scalar() == 1            # items were NOT cascade-deleted
        row = c.execute(text("SELECT status, payment_status, payment_method, area FROM orders")).one()
        assert tuple(row) == ("confirmed", "paid", "simulated", "")
        assert c.execute(text("SELECT delta_available, delta_reserved, reason FROM stock_movements")).one() == (90, 10, "initial_stock")
    with eng.begin() as c:                                                                  # the wider status set is now allowed
        c.execute(text("UPDATE orders SET status='awaiting_payment'"))
        c.execute(text("UPDATE orders SET status='payment_failed'"))
    with eng.connect() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert "ix_orders_user_created" in {r[1] for r in c.exec_driver_sql("PRAGMA index_list(orders)")}
