"""Checkout: persistence, snapshots, stock reservation, rollback, concurrency, ownership, cancellation."""
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import AuditEvent, Inventory, Order, Product
from app.factory import create_app
from app.schemas.store import OrderCreate
from app.services import order_service
from app.services.cart_service import add_item

from .conftest import ORDER_BODY, admin_h, auth, cust, order_body, pid, put_in_cart, stock


def checkout(client, headers, **over):
    return client.post("/orders", json=order_body(**over), headers=headers)


def test_checkout_requires_sign_in(client):
    assert client.post("/orders", json=order_body()).status_code == 401


def test_successful_checkout_persists_order_and_reduces_stock(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 3)
    put_in_cart(client, h, "DEMO-DE-002", 2)                           # eggs, offer price 49.99
    before = stock(client, "DEMO-FP-001"), stock(client, "DEMO-DE-002")
    r = checkout(client, h)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["reference"].startswith("ORD-") and o["status"] == "confirmed"
    assert o["subtotal_cents"] == 3 * 2499 + 2 * 4999 and o["delivery_fee_cents"] == 3500
    assert o["total_cents"] == o["subtotal_cents"] + 3500 and o["currency"] == "ZAR"
    assert o["payment_mode"] == "SIMULATED" and "no money" in o["payment_notice"].lower()
    assert {i["sku"] for i in o["items"]} == {"DEMO-FP-001", "DEMO-DE-002"}
    assert (stock(client, "DEMO-FP-001"), stock(client, "DEMO-DE-002")) == (before[0] - 3, before[1] - 2)
    assert client.get("/cart", headers=h).json()["items"] == []        # cart emptied
    got = client.get(f"/orders/{o['id']}", headers=h).json()
    assert got["reference"] == o["reference"] and len(got["items"]) == 2


def test_reserved_quantity_tracks_open_orders(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 4)
    checkout(client, h)
    with client.app.state.db.session() as s:
        inv = s.scalar(select(Inventory).where(Inventory.product_id == pid(client, "DEMO-FP-001")))
        assert inv.reserved_quantity == 4


def test_order_snapshots_survive_catalogue_changes(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    o = checkout(client, h).json()
    with client.app.state.db.session() as s:
        p = s.scalar(select(Product).where(Product.sku == "DEMO-FP-001"))
        p.name, p.price_cents = "Renamed Bananas", 99999
    again = client.get(f"/orders/{o['id']}", headers=h).json()
    assert again["items"][0]["name"] == "Bananas" and again["items"][0]["unit_price_cents"] == 2499
    assert again["total_cents"] == o["total_cents"]


def test_collection_has_no_delivery_fee_and_needs_no_address(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    body = {"fulfilment": "collection", "contact": ORDER_BODY["contact"]}
    o = client.post("/orders", json=body, headers=h).json()
    assert o["delivery_fee_cents"] == 0 and o["address_line"] == "" and o["fulfilment"] == "collection"


def test_delivery_requires_a_served_address(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    r = client.post("/orders", json={"fulfilment": "delivery", "contact": ORDER_BODY["contact"]}, headers=h)
    assert r.status_code == 422 and "address" in r.json()["detail"].lower()
    far = {**ORDER_BODY["address"], "city": "Lusaka"}
    r = checkout(client, h, address=far)
    assert r.status_code == 422 and "do not deliver to Lusaka" in r.json()["detail"]
    assert stock(client, "DEMO-FP-001") == 120                          # nothing reserved by the failed attempts
    assert client.get("/cart", headers=h).json()["item_count"] == 1     # cart kept so the shopper can fix the address


@pytest.mark.parametrize("extra", [{"card_number": "4111111111111111"}, {"cvv": "123"}, {"expiry": "12/30"}])
def test_card_data_is_rejected_not_collected(client, extra):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    body = order_body(payment={"method": "simulated", **extra})
    r = checkout(client, h, payment=body["payment"])
    assert r.status_code == 422
    assert "4111" not in r.text                                          # the value is never echoed back
    r = client.post("/orders", json={**order_body(), **extra}, headers=h)
    assert r.status_code == 422 and "4111" not in r.text


def test_order_does_not_expose_or_store_payment_credentials(client):
    cols = {c.name for c in Order.__table__.columns}
    assert not cols & {"card_number", "cvv", "card", "pan", "expiry"}


def test_unknown_payment_method_rejected(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    assert checkout(client, h, payment={"method": "card"}).status_code == 422


def test_empty_cart_cannot_check_out(client):
    r = checkout(client, cust())
    assert r.status_code == 409 and "empty" in r.json()["detail"].lower()


@pytest.mark.parametrize("contact", [{"name": "X", "email": "a@b.co", "phone": "0821234567"},
                                     {"name": "Okay Name", "email": "not-an-email", "phone": "0821234567"},
                                     {"name": "Okay Name", "email": "a@b.co", "phone": "abc"}])
def test_contact_validation(client, contact):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    assert checkout(client, h, contact=contact).status_code == 422


def test_stock_conflict_rolls_back_every_line(client):
    """Line 1 is available, line 2 is not: the whole order fails and line 1's stock is NOT deducted."""
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 5)
    put_in_cart(client, h, "DEMO-DE-003", 4)                            # cheddar: 5 in stock
    client.patch(f"/inventory/{pid(client, 'DEMO-DE-003')}", json={"set_available": 1, "reason": "sold in store"},
                 headers=admin_h())
    r = checkout(client, h)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["problems"][0]["name"] == "Cheddar Cheese" and d["problems"][0]["available"] == 1
    assert "Only 1" in d["problems"][0]["message"]
    assert stock(client, "DEMO-FP-001") == 120 and stock(client, "DEMO-DE-003") == 1       # unchanged
    assert client.get("/orders", headers=h).json()["total"] == 0                            # no order saved
    assert client.get("/cart", headers=h).json()["item_count"] == 9                         # cart preserved
    with client.app.state.db.session() as s:
        inv = s.scalar(select(Inventory).where(Inventory.product_id == pid(client, "DEMO-FP-001")))
        assert inv.reserved_quantity == 0


def test_out_of_stock_item_in_cart_blocks_checkout(client):
    h = cust()
    put_in_cart(client, h, "DEMO-DE-003", 2)
    client.patch(f"/inventory/{pid(client, 'DEMO-DE-003')}", json={"set_available": 0, "reason": "sold out"}, headers=admin_h())
    r = checkout(client, h)
    assert r.status_code == 409 and "out of stock" in r.json()["detail"]["problems"][0]["message"].lower()


def test_inactive_product_blocks_checkout(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    with client.app.state.db.session() as s:
        s.scalar(select(Product).where(Product.sku == "DEMO-FP-001")).is_active = False
    r = checkout(client, h)
    assert r.status_code == 409 and "no longer available" in r.json()["detail"]["problems"][0]["message"]


def test_currency_mismatch_is_refused_not_mixed(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    with client.app.state.db.session() as s:
        s.scalar(select(Product).where(Product.sku == "DEMO-FP-001")).currency = "ZMW"
    r = checkout(client, h)
    assert r.status_code == 409 and "ZMW" in r.json()["detail"]["problems"][0]["message"]
    r = put_in_cart(client, h, "DEMO-FP-001", 1)                         # also refused when adding to the cart
    assert r.status_code == 409


def test_stock_reservation_is_audited(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 2)
    o = checkout(client, h).json()
    with client.app.state.db.session() as s:
        actions = [a.action for a in s.scalars(select(AuditEvent).where(AuditEvent.entity_id == o["id"]))]
    assert "inventory.reserved" in actions and "order.created" in actions


# ---------------------------------------------------------------- concurrency
def test_concurrent_checkouts_never_oversell_service_level(client):
    """Eight shoppers each want 2 of a product with 5 units: exactly 2 orders can succeed (4 units)."""
    db, s = client.app.state.db, client.app.state.settings
    sku = "DEMO-DE-003"                                                  # 5 in stock
    product = pid(client, sku)
    users = [type("U", (), {"id": f"racer-{i}", "role": "customer"})() for i in range(8)]
    for u in users:
        with db.session() as session:
            add_item(session, u.id, product, 2, s)
    results, barrier = [], threading.Barrier(len(users))

    def worker(u):
        barrier.wait()
        try:
            with db.session() as session:
                order_service.create_order(session, u, OrderCreate.model_validate(order_body()), s)
            results.append("ok")
        except order_service.CheckoutRejected:
            results.append("rejected")
        except Exception as exc:                                         # pragma: no cover - would be a bug
            results.append(f"error:{type(exc).__name__}:{exc}")

    threads = [threading.Thread(target=worker, args=(u,)) for u in users]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 2 and results.count("rejected") == 6, results
    with db.session() as session:
        inv = session.scalar(select(Inventory).where(Inventory.product_id == product))
        assert inv.available_quantity == 1 and inv.reserved_quantity == 4
        assert inv.available_quantity >= 0


def test_concurrent_checkouts_never_oversell_over_http(client):
    sku, product = "DEMO-DE-003", pid(client, "DEMO-DE-003")            # 5 in stock
    for i in range(6):
        assert client.post("/cart/items", json={"product_id": product, "quantity": 1}, headers=cust(f"http-{i}")).status_code == 201
    # all six want 1 unit; only 5 exist
    codes, barrier = [], threading.Barrier(6)

    def worker(i):
        barrier.wait()
        codes.append(checkout(client, cust(f"http-{i}")).status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [201] * 5 + [409], codes
    assert stock(client, sku) == 0


def test_double_submit_creates_one_order(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    first, second = checkout(client, h), checkout(client, h)
    assert first.status_code == 201 and second.status_code == 409
    assert client.get("/orders", headers=h).json()["total"] == 1


# ---------------------------------------------------------------- ownership
def test_orders_are_private_to_their_owner(client):
    a, b = cust("alice"), cust("bob")
    put_in_cart(client, a, "DEMO-FP-001", 1)
    o = checkout(client, a).json()
    assert client.get(f"/orders/{o['id']}", headers=b).status_code == 404        # same answer as "does not exist"
    assert client.get("/orders", headers=b).json()["total"] == 0
    assert client.post(f"/orders/{o['id']}/cancel", headers=b).status_code == 404
    assert client.get("/orders/not-a-uuid", headers=a).status_code == 404
    assert client.get("/orders?all=true", headers=b).status_code == 403          # customers cannot widen the scope


def test_staff_can_view_all_orders(client):
    put_in_cart(client, cust("alice"), "DEMO-FP-001", 1)
    checkout(client, cust("alice"))
    staff = auth("ann", "fraud_analyst")
    assert client.get("/orders?all=true", headers=staff).json()["total"] == 1
    oid = client.get("/orders?all=true", headers=staff).json()["items"][0]["id"]
    assert client.get(f"/orders/{oid}", headers=staff).status_code == 200
    assert client.patch(f"/orders/{oid}/status", json={"status": "picking"}, headers=staff).status_code == 403


def test_order_history_pagination_and_order(client):
    h = cust()
    for _ in range(3):
        put_in_cart(client, h, "DEMO-FP-001", 1)
        checkout(client, h)
    d = client.get("/orders?page_size=2", headers=h).json()
    assert d["total"] == 3 and len(d["items"]) == 2
    assert d["items"][0]["created_at"] >= d["items"][1]["created_at"]


# ---------------------------------------------------------------- cancellation and status
def test_customer_cancel_restocks_exactly_once(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 4)
    o = checkout(client, h).json()
    assert stock(client, "DEMO-FP-001") == 116
    r = client.post(f"/orders/{o['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert stock(client, "DEMO-FP-001") == 120
    again = client.post(f"/orders/{o['id']}/cancel", headers=h)
    assert again.status_code == 409 and stock(client, "DEMO-FP-001") == 120      # no double restock
    with client.app.state.db.session() as s:
        inv = s.scalar(select(Inventory).where(Inventory.product_id == pid(client, "DEMO-FP-001")))
        assert inv.reserved_quantity == 0


def test_concurrent_cancels_restock_once(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 4)
    o = checkout(client, h).json()
    codes, barrier = [], threading.Barrier(4)

    def worker():
        barrier.wait()
        codes.append(client.post(f"/orders/{o['id']}/cancel", headers=h).status_code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes.count(200) == 1, codes
    assert stock(client, "DEMO-FP-001") == 120


def test_customer_cannot_cancel_after_preparation_starts(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    o = checkout(client, h).json()
    assert client.patch(f"/orders/{o['id']}/status", json={"status": "picking"}, headers=admin_h()).status_code == 200
    assert client.post(f"/orders/{o['id']}/cancel", headers=h).status_code == 409
    assert client.post(f"/orders/{o['id']}/cancel", headers=admin_h()).status_code == 200   # admin still can


def test_status_transitions_and_completion_releases_reservation(client):
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 2)
    o = checkout(client, h).json()
    ah = admin_h()
    assert client.patch(f"/orders/{o['id']}/status", json={"status": "completed"}, headers=ah).status_code == 409   # skipping steps
    for step in ("picking", "ready", "completed"):
        assert client.patch(f"/orders/{o['id']}/status", json={"status": step}, headers=ah).status_code == 200
    assert stock(client, "DEMO-FP-001") == 118                           # sold stock does not return
    with client.app.state.db.session() as s:
        inv = s.scalar(select(Inventory).where(Inventory.product_id == pid(client, "DEMO-FP-001")))
        assert inv.reserved_quantity == 0
    assert client.patch(f"/orders/{o['id']}/status", json={"status": "cancelled"}, headers=ah).status_code == 409


def test_checkout_rate_limit(settings):
    settings.checkout_rate_limit_per_min = 2
    with TestClient(create_app(settings)) as c:
        h = cust()
        codes = [checkout(c, h).status_code for _ in range(4)]
    assert 429 in codes


def test_customer_checkout_never_uses_the_model(client, monkeypatch):
    """Customer checkout must not send retail fields to the PCA/payment model."""
    from app.ml.predict import Predictor
    monkeypatch.setattr(Predictor, "predict", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 1)
    assert checkout(client, h).status_code == 201


def test_checkout_failure_leaves_no_partial_state_when_database_errors(client, monkeypatch):
    """An unexpected error half-way through (after stock was deducted) rolls everything back."""
    h = cust()
    put_in_cart(client, h, "DEMO-FP-001", 3)
    real = order_service.SimulatedPaymentAdapter.authorize

    def boom(self, **kw):
        raise RuntimeError("payment adapter exploded")

    monkeypatch.setattr(order_service.SimulatedPaymentAdapter, "authorize", boom)
    with TestClient(client.app, raise_server_exceptions=False) as c2:
        r = checkout(c2, h)
    assert r.status_code == 500 and "payment adapter exploded" not in r.text
    monkeypatch.setattr(order_service.SimulatedPaymentAdapter, "authorize", real)
    assert stock(client, "DEMO-FP-001") == 120                           # the deduction was rolled back
    assert client.get("/orders", headers=h).json()["total"] == 0
    assert checkout(client, h).status_code == 201                        # and the shopper can simply try again
