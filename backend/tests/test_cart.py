"""Server-side cart: validation, ownership and stock revalidation."""
from .conftest import admin_h, auth, cust, pid, put_in_cart


def test_cart_requires_sign_in(client):
    assert client.get("/cart").status_code == 401
    assert client.post("/cart/items", json={"product_id": 1, "quantity": 1}).status_code == 401


def test_empty_cart(client):
    d = client.get("/cart", headers=cust()).json()
    assert d["items"] == [] and d["subtotal_cents"] == 0 and d["delivery_fee_cents"] == 0 and d["currency"] == "ZMW"


def test_add_merge_update_remove_and_totals(client):
    h = cust()
    assert put_in_cart(client, h, "DEMO-FP-001", 2).status_code == 201
    d = put_in_cart(client, h, "DEMO-FP-001", 3).json()            # same product merges
    assert len(d["items"]) == 1 and d["items"][0]["quantity"] == 5 and d["item_count"] == 5
    assert d["subtotal_cents"] == 5 * 2499 and d["delivery_fee_cents"] == 3500        # below the free-delivery threshold
    item_id = d["items"][0]["item_id"]
    d = client.patch(f"/cart/items/{item_id}", json={"quantity": 2}, headers=h).json()
    assert d["items"][0]["quantity"] == 2 and d["subtotal_cents"] == 4998
    d = client.delete(f"/cart/items/{item_id}", headers=h).json()
    assert d["items"] == []


def test_offer_price_is_used(client):
    d = put_in_cart(client, cust(), "DEMO-FP-002", 1).json()          # apples: 39.99, offer 32.99
    assert d["items"][0]["line_total_cents"] == 3299


def test_free_delivery_over_threshold(client):
    d = put_in_cart(client, cust(), "DEMO-MP-002", 7).json()          # 7 x 99.99 = 699.93 > 600
    assert d["subtotal_cents"] > 60000 and d["delivery_fee_cents"] == 0


def test_out_of_stock_rejected_with_clear_message(client):
    r = put_in_cart(client, cust(), "DEMO-FP-004", 1)
    assert r.status_code == 409 and "out of stock" in r.json()["detail"].lower()


def test_quantity_above_stock_rejected(client):
    r = put_in_cart(client, cust(), "DEMO-DE-003", 6)                  # only 5 in stock
    assert r.status_code == 409 and "Only 5" in r.json()["detail"]
    assert put_in_cart(client, cust(), "DEMO-DE-003", 5).status_code == 201
    r = put_in_cart(client, cust(), "DEMO-DE-003", 1)                  # merged total 6 > 5
    assert r.status_code == 409


def test_per_line_limit(client):
    r = put_in_cart(client, cust(), "DEMO-PA-005", 21)                 # plenty of stock, but max 20 per line
    assert r.status_code == 409 and "at most 20" in r.json()["detail"]


def test_invalid_quantities_and_ids(client):
    h = cust()
    for body in ({"product_id": 1, "quantity": 0}, {"product_id": 1, "quantity": -3}, {"product_id": 0, "quantity": 1},
                 {"product_id": 1, "quantity": 1, "price_cents": 1}, {"product_id": "x", "quantity": 1}):
        assert client.post("/cart/items", json=body, headers=h).status_code == 422, body
    assert client.post("/cart/items", json={"product_id": 99999, "quantity": 1}, headers=h).status_code == 404


def test_carts_are_private(client):
    d = put_in_cart(client, cust("a"), "DEMO-FP-001", 1).json()
    item_id = d["items"][0]["item_id"]
    other = cust("b")
    assert client.get("/cart", headers=other).json()["items"] == []
    assert client.patch(f"/cart/items/{item_id}", json={"quantity": 9}, headers=other).status_code == 404
    assert client.delete(f"/cart/items/{item_id}", headers=other).status_code == 404
    assert client.get("/cart", headers=cust("a")).json()["items"][0]["quantity"] == 1     # untouched


def test_cart_revalidates_stock_on_every_read(client):
    h = cust()
    put_in_cart(client, h, "DEMO-DE-003", 4)
    client.patch(f"/inventory/{pid(client, 'DEMO-DE-003')}", json={"set_available": 2, "reason": "shrinkage"}, headers=admin_h())
    d = client.get("/cart", headers=h).json()
    assert d["has_issues"] and d["items"][0]["issue"] == "quantity_exceeds_stock"
    client.patch(f"/inventory/{pid(client, 'DEMO-DE-003')}", json={"set_available": 0, "reason": "shrinkage"}, headers=admin_h())
    assert client.get("/cart", headers=h).json()["items"][0]["issue"] == "out_of_stock"


def test_update_cannot_exceed_stock(client):
    h = cust()
    d = put_in_cart(client, h, "DEMO-DE-003", 1).json()
    r = client.patch(f"/cart/items/{d['items'][0]['item_id']}", json={"quantity": 6}, headers=h)
    assert r.status_code == 409


def test_cart_rate_limit(settings):
    from fastapi.testclient import TestClient
    from app.factory import create_app
    settings.cart_rate_limit_per_min = 3
    with TestClient(create_app(settings)) as c:
        codes = [put_in_cart(c, cust(), "DEMO-FP-001", 1).status_code for _ in range(5)]
    assert codes[:3] == [201, 201, 201] and 429 in codes[3:]
