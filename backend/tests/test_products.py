"""Catalogue, categories, stock labels and seed data. Stock comes from the database, never from the UI."""
import pytest
from sqlalchemy import func, select

from app.db.models import Inventory, Product
from app.db.seed import seed_catalogue

from .conftest import admin_h, cust, pid, stock


def test_catalogue_is_public_and_paginated(client):
    r = client.get("/products?page_size=10")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 40 and len(d["items"]) == 10 and d["page"] == 1
    p = d["items"][0]
    for key in ("id", "sku", "name", "description", "price_cents", "currency", "image_ref", "stock_status",
                "available_quantity", "effective_price_cents", "category_slug"):
        assert key in p
    assert p["currency"] == "ZMW" and p["is_demo"] is True


def test_categories_have_counts(client):
    cats = client.get("/categories").json()
    assert len(cats) == 8 and sum(c["product_count"] for c in cats) == 40


def test_search_filter_sort(client):
    assert {p["name"] for p in client.get("/products?search=banana").json()["items"]} == {"Bananas"}
    pct = client.get("/products?search=%25").json()                                     # a literal "%", not a wildcard
    assert [p["name"] for p in pct["items"]] == ["Orange Juice"]                        # the only text containing "100%"
    assert client.get("/products?search=_").json()["total"] == 0                        # "_" is not a single-char wildcard
    dairy = client.get("/products?category=dairy-eggs").json()
    assert dairy["total"] == 5 and all(p["category_slug"] == "dairy-eggs" for p in dairy["items"])
    prices = [p["effective_price_cents"] for p in client.get("/products?sort=price_asc&page_size=60").json()["items"]]
    assert prices == sorted(prices)
    cheap = client.get("/products?max_price=20&page_size=60").json()["items"]
    assert cheap and all(p["effective_price_cents"] <= 2000 for p in cheap)
    assert all(p["offer_price_cents"] is not None for p in client.get("/products?on_offer=true&page_size=60").json()["items"])
    assert all(p["stock_status"] != "out_of_stock" for p in client.get("/products?in_stock_only=true&page_size=60").json()["items"])
    assert all(p["is_featured"] for p in client.get("/products?featured=true&page_size=60").json()["items"])


@pytest.mark.parametrize("q", ["page=0", "page_size=500", "sort=banana", "min_price=-1", "category=Bad%20Slug"])
def test_bad_query_rejected(client, q):
    assert client.get(f"/products?{q}").status_code == 422


def test_stock_labels_come_from_database(client, settings):
    by_sku = {p["sku"]: p for p in client.get("/products?page_size=60").json()["items"]}
    assert by_sku["DEMO-FP-004"]["stock_status"] == "out_of_stock" and by_sku["DEMO-FP-004"]["available_quantity"] == 0
    assert by_sku["DEMO-DE-003"]["stock_status"] == "low_stock" and by_sku["DEMO-DE-003"]["available_quantity"] == 5
    assert by_sku["DEMO-FP-001"]["stock_status"] == "in_stock"
    # change the database row: the API follows it (nothing is hard-coded in the client or the response)
    r = client.patch(f"/inventory/{pid(client, 'DEMO-FP-001')}", json={"set_available": 0, "reason": "test stock-out"},
                     headers=admin_h())
    assert r.status_code == 200
    assert client.get(f"/products/{pid(client, 'DEMO-FP-001')}").json()["stock_status"] == "out_of_stock"


def test_product_detail_and_404(client):
    p = client.get(f"/products/{pid(client, 'DEMO-FP-001')}").json()
    assert p["name"] == "Bananas" and "Demonstration" in p["description"]
    assert client.get("/products/999999").status_code == 404


def test_store_info_is_labelled_demo(client):
    d = client.get("/store-info").json()
    assert d["is_demo"] is True and d["currency"] == "ZMW"
    assert "not affiliated" in d["disclaimer"] and "simulated" in d["disclaimer"].lower()


def test_seed_is_idempotent_and_never_overwrites(client, settings):
    db = client.app.state.db
    with db.session() as s:
        s.execute(Product.__table__.update().where(Product.sku == "DEMO-FP-001").values(name="Renamed by owner"))
        s.execute(Inventory.__table__.update().where(Inventory.product_id == 1).values(available_quantity=7))
    with db.session() as s:
        assert seed_catalogue(s, "ZMW") == {"categories": 0, "products": 0}
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(Product)) == 40
        assert s.scalar(select(Product.name).where(Product.sku == "DEMO-FP-001")) == "Renamed by owner"
        assert s.scalar(select(Inventory.available_quantity).where(Inventory.product_id == 1)) == 7


def test_inventory_constraints_reject_negative_stock(client):
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        with client.app.state.db.session() as s:
            s.execute(Inventory.__table__.update().where(Inventory.product_id == 1).values(available_quantity=-1))


def test_responses_carry_correlation_id_and_security_headers(client):
    r = client.get("/products")
    assert r.headers["x-request-id"] and r.headers["x-content-type-options"] == "nosniff"
    r2 = client.get("/products", headers={"X-Request-ID": "my-trace-id-12345"})
    assert r2.headers["x-request-id"] == "my-trace-id-12345"
    r3 = client.get("/products", headers={"X-Request-ID": "bad id with spaces!"})
    assert r3.headers["x-request-id"] != "bad id with spaces!"
