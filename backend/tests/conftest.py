"""Test fixtures. Tokens are signed with a TEST secret; nothing here talks to a real Supabase project."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.sqlite_repo import SqliteRepository
from app.factory import create_app
from app.ml import feature_schema as fs
from app.ml.predict import Predictor
from app.ml.synthetic import generate
from app.ml.train_model import save_artifact, train

SECRET = "test-secret-test-secret-test-secret-123"


def make_token(sub="user-a", role="fraud_analyst", secret=SECRET, exp_in=3600, aud="authenticated"):
    claims = {"sub": sub, "aud": aud, "exp": int(time.time()) + exp_in, "email": f"{sub}@example.com"}
    if role:
        claims["app_metadata"] = {"role": role}
    return jwt.encode(claims, secret, algorithm="HS256")


def auth(sub="user-a", role="fraud_analyst", **kw):
    return {"Authorization": f"Bearer {make_token(sub, role, **kw)}"}


@pytest.fixture(scope="session")
def model_path(tmp_path_factory):
    """A small controlled model trained on a synthetic fixture (fast)."""
    path = tmp_path_factory.mktemp("model") / "m.joblib"
    pipe, meta = train(generate(3000, seed=1), "synthetic-test", True, n_estimators=30)
    save_artifact(pipe, meta, path)
    return path


LOCAL_SECRET = "local-demo-secret-local-demo-secret-0123456789"


@pytest.fixture()
def settings(tmp_path, model_path):
    return Settings(db_backend="sqlite", sqlite_path=tmp_path / "t.db", supabase_jwt_secret=SECRET,
                    model_path=model_path, predict_rate_limit_per_min=1000,
                    database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}", seed_demo_data=True,
                    checkout_rate_limit_per_min=1000, cart_rate_limit_per_min=1000, scamwatch_rate_limit_per_min=1000,
                    scamwatch_providers="heuristic", _env_file=None)


@pytest.fixture()
def local_settings(settings):
    settings.local_auth_enabled = True
    settings.local_auth_secret = LOCAL_SECRET
    return settings


@pytest.fixture()
def local_client(local_settings):
    with TestClient(create_app(local_settings)) as c:
        yield c


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture()
def client_no_model(settings, tmp_path):
    settings.model_path = tmp_path / "missing.joblib"
    with TestClient(create_app(settings)) as c:
        yield c


def valid_payload(**over):
    p = {"transaction_reference": "TX-1001", "amount": 250.0, "payment_method": "Card", "hour": 14,
         "failed_attempts": 0, "new_device": False, "international": False,
         "customer_avg_spend": 240.0, "branch": "Online"}
    p.update(over)
    return p


RISKY = dict(amount=9000.0, hour=2, failed_attempts=5, new_device=True, international=True,
             customer_avg_spend=100.0)


# ---------- store helpers ----------
CUSTOMER = ("cust-1", "customer")
CUSTOMER_2 = ("cust-2", "customer")


def cust(sub="cust-1"):
    return auth(sub, "customer")


def admin_h():
    return auth("admin-1", "admin")


def pid(client, sku):
    items = client.get(f"/products?search={sku}").json()["items"]
    assert items, f"seed product {sku} missing"
    return items[0]["id"]


def put_in_cart(client, headers, sku, qty=1):
    return client.post("/cart/items", json={"product_id": pid(client, sku), "quantity": qty}, headers=headers)


ORDER_BODY = {"fulfilment": "delivery",
              "contact": {"name": "Test Shopper", "email": "shopper@example.com", "phone": "0821234567"},
              "address": {"line": "12 Test Street", "city": "Johannesburg", "postal_code": "2000"}}


def order_body(**over):
    body = {**ORDER_BODY, **over}
    return body


def stock(client, sku):
    return client.get(f"/products/{pid(client, sku)}").json()["available_quantity"]
