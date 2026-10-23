"""Catalogue administration: products, categories, price history, stock ledger, permissions."""
import pytest
from sqlalchemy import select

from app.db.models import AuditEvent, PriceHistory, Product
from app.services.stock_ledger import mismatches

from .conftest import admin_h, auth, cust

FRAUD = auth("fraud-1", "fraud_analyst")


def new_product(client, **over):
    body = {"sku": "ZM-TEST-001", "name": "Test Mealie Meal", "category_slug": "fresh-produce", "price_cents": 12500,
            "initial_quantity": 40, "unit": "each", "brand": "Test Mills", "pack_size": "25 kg"}
    body.update(over)
    return client.post("/admin/products", json=body, headers=admin_h())


@pytest.fixture()
def cat(client):
    slug = client.get("/categories").json()[0]["slug"]
    return slug


def test_only_administrators_can_manage_the_catalogue(client, cat):
    body = {"sku": "ZM-X-1", "name": "Nope", "category_slug": cat, "price_cents": 100}
    for h in (cust(), FRAUD, auth("sec-1", "security_analyst")):
        assert client.post("/admin/products", json=body, headers=h).status_code == 403
        assert client.get("/admin/products", headers=h).status_code == 403
        assert client.patch("/admin/products/1", json={"name": "x y"}, headers=h).status_code == 403
        assert client.post("/admin/categories", json={"name": "Hack"}, headers=h).status_code == 403
    assert client.post("/admin/products", json=body).status_code == 401


def test_creating_a_product_makes_it_buyable_with_stock_price_history_and_audit(client, cat):
    r = new_product(client, category_slug=cat)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["sku"] == "ZM-TEST-001" and p["currency"] == "ZMW" and p["available_quantity"] == 40
    assert p["price_status"] == "verified" and p["is_demo"] is False and p["effective_price_cents"] == 12500
    pub = client.get(f"/products/{p['id']}").json()
    assert pub["name"] == "Test Mealie Meal" and pub["available_quantity"] == 40 and pub["brand"] == "Test Mills"
    with client.app.state.db.session() as s:
        assert mismatches(s) == []                                                   # ledger and inventory agree
        assert len(s.scalars(select(PriceHistory).where(PriceHistory.product_id == p["id"])).all()) == 1
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "product.created")) is not None
    hist = client.get(f"/admin/products/{p['id']}/price-history", headers=admin_h()).json()["items"]
    assert hist[0]["price_cents"] == 12500 and hist[0]["recorded_by"] == "admin-1"


def test_validation_and_conflicts(client, cat):
    assert new_product(client, category_slug=cat).status_code == 201
    assert new_product(client, category_slug=cat).status_code == 409                  # duplicate SKU
    assert new_product(client, sku="bad sku!", category_slug=cat).status_code == 422
    assert new_product(client, category_slug="no-such-category").status_code == 422
    assert new_product(client, sku="ZM-NEG-1", category_slug=cat, price_cents=-1).status_code == 422
    assert new_product(client, sku="ZM-BIG-1", category_slug=cat, price_cents=99_999_999).status_code == 422   # typo guard
    assert new_product(client, sku="ZM-OFF-1", category_slug=cat, offer_price_cents=20000).status_code == 422  # offer >= price
    assert new_product(client, sku="ZM-IMG-1", category_slug=cat, image_ref="javascript:alert(1)").status_code == 422
    assert new_product(client, sku="ZM-IMG-2", category_slug=cat, image_ref="http://insecure.example/x.jpg").status_code == 422
    assert new_product(client, sku="ZM-IMG-3", category_slug=cat, image_ref="https://cdn.example.com/x.jpg").status_code == 201
    assert new_product(client, sku="ZM-IMG-4", category_slug=cat, image_ref="/products/x.jpg").status_code == 201
    assert new_product(client, sku="ZM-DATE-1", category_slug=cat, offer_price_cents=100,
                       offer_starts_on="2026-12-01", offer_ends_on="2026-11-01").status_code == 422
    assert new_product(client, sku="ZM-XTRA-1", category_slug=cat, is_admin=True).status_code == 422          # unknown field


def test_changing_a_price_is_recorded_and_offers_can_be_set_and_cleared(client, cat):
    p = new_product(client, category_slug=cat).json()
    r = client.patch(f"/admin/products/{p['id']}", json={"price_cents": 14000, "offer_price_cents": 11000}, headers=admin_h())
    assert r.status_code == 200 and r.json()["effective_price_cents"] == 11000
    assert client.get(f"/products/{p['id']}").json()["effective_price_cents"] == 11000
    assert client.patch(f"/admin/products/{p['id']}", json={"offer_price_cents": 15000}, headers=admin_h()).status_code == 422
    assert client.patch(f"/admin/products/{p['id']}", json={"clear_offer": True}, headers=admin_h()).json()["effective_price_cents"] == 14000
    hist = client.get(f"/admin/products/{p['id']}/price-history", headers=admin_h()).json()["items"]
    assert [h["price_cents"] for h in hist] == [14000, 14000, 12500] and hist[1]["offer_price_cents"] == 11000
    with client.app.state.db.session() as s:
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "product.price_changed")) is not None


def test_deactivating_hides_the_product_but_never_deletes_it(client, cat):
    p = new_product(client, category_slug=cat).json()
    r = client.patch(f"/admin/products/{p['id']}", json={"is_active": False}, headers=admin_h())
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get(f"/products/{p['id']}").status_code == 404
    assert client.get("/products?search=ZM-TEST", headers=cust()).json()["total"] == 0
    assert client.get("/admin/products?search=ZM-TEST", headers=admin_h()).json()["total"] == 1      # still listed for admins
    assert client.get("/admin/products?search=ZM-TEST&include_inactive=false", headers=admin_h()).json()["total"] == 0
    assert client.delete(f"/admin/products/{p['id']}", headers=admin_h()).status_code == 405
    client.patch(f"/admin/products/{p['id']}", json={"is_active": True}, headers=admin_h())
    assert client.get(f"/products/{p['id']}").status_code == 200


def test_editing_details_and_moving_category(client):
    cats = client.get("/categories").json()
    p = new_product(client, category_slug=cats[0]["slug"]).json()
    r = client.patch(f"/admin/products/{p['id']}", json={"name": "Renamed Meal", "category_slug": cats[1]["slug"],
                                                         "description": "Fine white mealie meal", "is_featured": True,
                                                         "image_ref": "/products/meal.jpg"}, headers=admin_h())
    d = r.json()
    assert d["name"] == "Renamed Meal" and d["category_slug"] == cats[1]["slug"] and d["is_featured"] is True
    assert d["image_status"] == "licensed" and d["price_cents"] == 12500
    assert client.patch(f"/admin/products/{p['id']}", json={"category_slug": "nope"}, headers=admin_h()).status_code == 422
    assert client.patch("/admin/products/999999", json={"name": "zz"}, headers=admin_h()).status_code == 404
    assert client.patch(f"/admin/products/{p['id']}", json={"price_cents": 99999999}, headers=admin_h()).status_code == 422


def test_categories_can_be_created_once(client):
    r = client.post("/admin/categories", json={"name": "Fresh Fish & Kapenta"}, headers=admin_h())
    assert r.status_code == 201 and r.json()["slug"] == "fresh-fish-kapenta"
    assert client.post("/admin/categories", json={"name": "Fresh Fish & Kapenta"}, headers=admin_h()).status_code == 409
    assert client.post("/admin/categories", json={"name": "!!!"}, headers=admin_h()).status_code == 422
    assert "fresh-fish-kapenta" in [c["slug"] for c in client.get("/categories").json()]
    p = new_product(client, category_slug="fresh-fish-kapenta")
    assert p.status_code == 201


def test_a_new_product_can_be_ordered_and_stock_stays_consistent(client, cat):
    p = new_product(client, category_slug=cat, initial_quantity=3).json()
    h = cust()
    assert client.post("/cart/items", json={"product_id": p["id"], "quantity": 2}, headers=h).status_code in (200, 201)
    r = client.post("/orders", json={"fulfilment": "collection", "contact": {"name": "Test Shopper", "email": "s@example.com",
                                                                            "phone": "0971234567"},
                                     "payment": {"method": "simulated", "scenario": "success"}}, headers=h)
    assert r.status_code == 201 and r.json()["total_cents"] == 25000
    assert client.get(f"/products/{p['id']}").json()["available_quantity"] == 1
    with client.app.state.db.session() as s:
        assert mismatches(s) == []


def test_console_admin_only_locks_analysts_out_but_not_administrators(settings):
    from fastapi.testclient import TestClient
    from app.factory import create_app
    settings.console_admin_only = True
    with TestClient(create_app(settings)) as c:
        assert c.get("/store-info").json()["console_admin_only"] is True
        for path in ("/staff/orders", "/investigations", "/reports/overview", "/inventory"):
            assert c.get(path, headers=FRAUD).status_code == 403, path
            assert c.get(path, headers=auth("sec-1", "security_analyst")).status_code == 403, path
            assert c.get(path, headers=admin_h()).status_code == 200, path
        assert c.get("/products").status_code == 200                           # the store itself is unaffected
        assert c.get("/cart", headers=FRAUD).status_code == 200                # analysts can still shop as customers


def test_analysts_keep_their_access_by_default(client):
    assert client.get("/store-info").json()["console_admin_only"] is False
    assert client.get("/staff/orders", headers=FRAUD).status_code == 200
