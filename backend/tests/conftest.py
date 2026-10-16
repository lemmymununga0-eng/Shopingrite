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


def make_token(sub="user-a", role=None, secret=SECRET, exp_in=3600, aud="authenticated"):
    claims = {"sub": sub, "aud": aud, "exp": int(time.time()) + exp_in, "email": f"{sub}@example.com"}
    if role:
        claims["app_metadata"] = {"role": role}
    return jwt.encode(claims, secret, algorithm="HS256")


def auth(sub="user-a", role=None, **kw):
    return {"Authorization": f"Bearer {make_token(sub, role, **kw)}"}


@pytest.fixture(scope="session")
def model_path(tmp_path_factory):
    """A small controlled model trained on a synthetic fixture (fast)."""
    path = tmp_path_factory.mktemp("model") / "m.joblib"
    pipe, meta = train(generate(3000, seed=1), "synthetic-test", True, n_estimators=30)
    save_artifact(pipe, meta, path)
    return path


@pytest.fixture()
def settings(tmp_path, model_path):
    return Settings(db_backend="sqlite", sqlite_path=tmp_path / "t.db", supabase_jwt_secret=SECRET,
                    model_path=model_path, predict_rate_limit_per_min=1000, _env_file=None)


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
