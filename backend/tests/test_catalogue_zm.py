"""Zambian catalogue: provenance, expiring offers, brand search, popularity sort, migration and legacy retirement."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text, select

from app.db import catalogue_zm as zm
from app.db.models import PriceHistory, Product
from app.factory import create_app

from .conftest import cust, put_in_cart, order_body


@pytest.fixture()
def zclient(settings):
    settings.seed_legacy_demo = False
    settings.seed_zm_catalogue = True
    with TestClient(create_app(settings)) as c:
        yield c


def test_catalogue_seeds_in_kwacha_with_provenance(zclient):
    d = zclient.get("/products?page_size=60&page=1").json()
    assert d["total"] == len(zm.P)
    assert all(p["currency"] == "ZMW" for p in d["items"])
    p = zclient.get("/products?search=Parmalat").json()["items"][0]
    assert p["brand"] == "Parmalat" and p["pack_size"] == "1 L" and p["price_status"] == "observed"
    assert p["price_source_url"].startswith("https://lusakadelivery.com/") and p["price_checked_on"] == "2026-10-17"
    est = zclient.get("/products?search=Onions").json()["items"][0]
    assert est["price_status"] == "estimated" and est["price_source_url"] == "" and est["price_checked_on"] is None


def test_no_product_claims_to_be_verified(zclient):
    items = zclient.get("/products?page_size=60").json()["items"]
    assert {p["price_status"] for p in items} <= {"observed", "estimated"}


def test_placeholder_images_are_flagged_and_licensed_ones_have_credit(zclient):
    for p in zclient.get("/products?page_size=60").json()["items"]:
        if p["image_status"] == "licensed":
            assert p["image_license"] and p["image_source"].startswith("https://commons.wikimedia.org/")
        else:
            assert p["image_ref"].endswith(".svg")
        assert p["image_alt"]


def test_price_history_written_for_every_seeded_product(zclient):
    with zclient.app.state.db.session() as s:
        n_hist = len(s.scalars(select(PriceHistory.product_id).distinct()).all())
        assert n_hist == len(zm.P)


def test_search_by_brand_and_sort_and_popularity(zclient):
    assert [p["brand"] for p in zclient.get("/products?search=zammilk").json()["items"]] == ["Zammilk"]
    asc = [p["effective_price_cents"] for p in zclient.get("/products?sort=price_asc&page_size=60").json()["items"]]
    assert asc == sorted(asc)
    h = cust()
    assert put_in_cart(zclient, h, "ZM-PA-002", 3).status_code == 201
    assert zclient.post("/orders", json=order_body(), headers=h).status_code == 201
    first = zclient.get("/products?sort=popular").json()["items"][0]
    assert first["sku"] == "ZM-PA-002"


def test_expired_offer_is_not_shown_or_charged(zclient):
    with zclient.app.state.db.session() as s:
        p = s.scalar(select(Product).where(Product.sku == "ZM-PA-001"))
        assert p.offer_price_cents is not None
        p.offer_ends_on = date.today() - timedelta(days=1)
    item = zclient.get("/products?search=ZM-PA-001").json()["items"][0]
    assert item["offer_price_cents"] is None and item["effective_price_cents"] == item["price_cents"]
    assert "ZM-PA-001" not in {p["sku"] for p in zclient.get("/products?on_offer=true&page_size=60").json()["items"]}
    h = cust()
    assert put_in_cart(zclient, h, "ZM-PA-001", 1).status_code == 201
    order = zclient.post("/orders", json=order_body(), headers=h).json()
    assert order["items"][0]["unit_price_cents"] == item["price_cents"]


def test_live_offer_is_shown_and_charged(zclient):
    item = zclient.get("/products?search=ZM-DE-004").json()["items"][0]
    assert item["offer_price_cents"] == 7900 and item["effective_price_cents"] == 7900
    assert item["offer_ends_on"] == "2026-11-30" or date.today() > date(2026, 11, 30)


def test_legacy_demo_products_are_retired_but_kept(settings):
    settings.seed_legacy_demo = True
    settings.seed_zm_catalogue = False
    with TestClient(create_app(settings)) as c:
        assert c.get("/products?search=DEMO-FP-001").json()["total"] == 1
    settings.seed_legacy_demo = False
    settings.seed_zm_catalogue = True
    with TestClient(create_app(settings)) as c:
        assert c.get("/products?search=DEMO-FP-001").json()["total"] == 0
        with c.app.state.db.session() as s:
            assert s.scalar(select(Product).where(Product.sku == "DEMO-FP-001")) is not None


def test_seed_is_idempotent_and_preserves_admin_edits(settings):
    settings.seed_legacy_demo = False
    settings.seed_zm_catalogue = True
    with TestClient(create_app(settings)) as c:
        with c.app.state.db.session() as s:
            s.scalar(select(Product).where(Product.sku == "ZM-PA-002")).price_cents = 5000
    with TestClient(create_app(settings)) as c:
        assert c.get("/products?search=ZM-PA-002").json()["items"][0]["price_cents"] == 5000
        assert c.get("/products?page_size=60").json()["total"] == len(zm.P)


def test_migration_2_adds_columns_to_an_existing_database(tmp_path, monkeypatch):
    from app.db import migrations as m
    eng = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with eng.begin() as conn:     # an old-style products table without the new columns
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, sku VARCHAR(40), name VARCHAR(160))"))
        conn.execute(text("INSERT INTO products (id, sku, name) VALUES (1, 'OLD-1', 'Old product')"))
    monkeypatch.setattr(m, "MIGRATIONS", [x for x in m.MIGRATIONS if x[0] == 2])   # baseline skipped: table exists
    assert m.migrate(eng) == [2]
    assert m.migrate(eng) == []
    cols = {c["name"] for c in inspect(eng).get_columns("products")}
    assert {"brand", "pack_size", "price_status", "price_source_url", "offer_ends_on", "image_status"} <= cols
    assert "price_history" in inspect(eng).get_table_names()
    with eng.connect() as conn:
        assert tuple(conn.execute(text("SELECT sku, price_status, brand FROM products")).one()) == ("OLD-1", "estimated", "")
