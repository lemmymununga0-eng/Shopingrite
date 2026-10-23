"""/fraud endpoints: honest status, strict input validation, authorization. Uses a small FIXTURE model, not real data."""
import json

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.ml import registry as reg
from tests.conftest import admin_h, auth, cust
from tests.test_ml_framework import fast_task, make_cc_fixture, trained  # noqa: F401  (fixture re-use)

FEATURES = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount"]


def row(**over):
    base = {f: 0.0 for f in FEATURES}
    base.update(over)
    return base


def test_status_when_nothing_is_trained(client):
    r = client.get("/fraud/model-status", headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert body["any_ready"] is False
    assert {m["state"] for m in body["models"]} == {"not_trained"}
    sc = body["store_scoring"]
    assert sc["method"] == "rules" and sc["rule_engine"] == "store_risk_v1" and sc["schema_version"] == "grocery_txn_v1"
    assert sc["labels"]["ready_to_train"] is False and sc["labels"]["verified_fraud"] == 0


def test_predict_without_a_model_is_503_and_gives_no_score(client):
    r = client.post("/fraud/predict", headers=auth(), json={"model": "creditcard_pca", "features": row()})
    assert r.status_code == 503
    assert "probability" not in json.dumps(r.json())


def test_customers_cannot_see_models_or_predict(client):
    assert client.get("/fraud/model-status", headers=cust()).status_code == 403
    assert client.post("/fraud/predict", headers=cust(), json={"model": "creditcard_pca", "features": row()}).status_code == 403
    assert client.get("/fraud/model-status").status_code in (401, 403)


@pytest.fixture()
def live(settings, trained):  # noqa: F811
    meta = json.loads(json.dumps(trained.metadata, default=str))
    meta["version"] = "v-fixture"
    reg.save_version("creditcard_pca", "v-fixture", trained.pipeline, meta, "report", None, settings.ml_artifact_dir)
    reg.promote("creditcard_pca", "v-fixture", settings.ml_artifact_dir)
    with TestClient(create_app(settings)) as c:
        yield c


def test_ready_model_reports_metadata_and_scores(live):
    st = live.get("/fraud/model-status", headers=auth()).json()
    cc = next(m for m in st["models"] if m["model"] == "creditcard_pca")
    assert cc["ready"] and cc["version"] == "v-fixture" and cc["is_fixture"] is True
    r = live.post("/fraud/predict", headers=auth(), json={"model": "creditcard_pca", "features": row(V3=3.0, V6=3.0, V9=3.0)})
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "ok" and 0 <= b["probability"] <= 1 and b["saved"] is False and b["model_version"] == "v-fixture"


def test_missing_and_unexpected_fields_are_rejected_not_filled(live):
    f = row()
    f.pop("V5")
    f["card_number"] = 1.0
    r = live.post("/fraud/predict", headers=auth(), json={"model": "creditcard_pca", "features": f})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["status"] == "unsupported_input_schema"
    assert d["missing_features"] == ["V5"] and d["unexpected_features"] == ["card_number"]


def test_store_order_fields_are_unsupported_by_the_card_model(live):
    r = live.post("/fraud/predict", headers=auth(),
                  json={"model": "creditcard_pca", "features": {"amount": 250.0, "hour": 14, "payment_method": "Card"}})
    assert r.status_code == 422 and r.json()["detail"]["status"] == "unsupported_input_schema"


@pytest.mark.parametrize("bad", [{"Amount": -5.0}, {"Amount": 1e12}])
def test_out_of_range_values_are_invalid_input(live, bad):
    r = live.post("/fraud/predict", headers=auth(), json={"model": "creditcard_pca", "features": row(**bad)})
    assert r.status_code == 422 and r.json()["detail"]["status"] == "invalid_input"


def test_non_numeric_and_unknown_model(live):
    assert live.post("/fraud/predict", headers=auth(), json={"model": "creditcard_pca", "features": row(V1="abc")}).status_code == 422
    assert live.post("/fraud/predict", headers=auth(), json={"model": "nope", "features": {}}).status_code == 422
    assert live.post("/fraud/predict", headers=auth(), json={"model": "creditcard_pca", "features": row(), "extra": 1}).status_code == 422


def test_a_tampered_artifact_is_refused_at_load(settings, trained):  # noqa: F811
    meta = json.loads(json.dumps(trained.metadata, default=str))
    meta["version"] = "v-t"
    path = reg.save_version("creditcard_pca", "v-t", trained.pipeline, meta, "", None, settings.ml_artifact_dir)
    reg.promote("creditcard_pca", "v-t", settings.ml_artifact_dir)
    (path / "model.joblib").write_bytes(b"tampered")
    with TestClient(create_app(settings)) as c:
        cc = next(m for m in c.get("/fraud/model-status", headers=admin_h()).json()["models"] if m["model"] == "creditcard_pca")
        assert cc["ready"] is False and cc["state"] != "ready"
        assert c.post("/fraud/predict", headers=auth(), json={"model": "creditcard_pca", "features": row()}).status_code == 503


# ------------------------------------------------------------------------------------------------ ScamWatch ml_url provider
from app.services.scamwatch_service import MlUrlProvider  # noqa: E402


class _Fake:
    def __init__(self, res):
        self.res = res

    def predict(self, name, features):
        assert name == "url_phishing" and set(features) == {"url"}
        return self.res


def test_ml_url_provider_is_skipped_when_the_model_is_not_ready():
    r = MlUrlProvider(_Fake({"status": "model_unavailable"})).check("http://x.test", "x.test", [])
    assert r.status == "skipped" and r.verdict == "inconclusive"


def test_ml_url_provider_never_says_safe_or_malicious():
    hi = MlUrlProvider(_Fake({"status": "ok", "flagged": True, "probability": 0.99, "model_version": "v1"})).check("u", "d", [])
    lo = MlUrlProvider(_Fake({"status": "ok", "flagged": False, "probability": 0.01, "model_version": "v1"})).check("u", "d", [])
    assert hi.verdict == "suspicious" and lo.verdict == "inconclusive"
    assert "not mean the site is safe" in lo.detail
    err = MlUrlProvider(_Fake({"status": "prediction_failed"})).check("u", "d", [])
    assert err.status == "error" and err.verdict == "inconclusive"


def test_pca_demo_uses_the_verified_model_when_one_is_ready(live):
    info = live.get("/pca-demo/info", headers=auth()).json()
    assert info["trained"] is True and info["source"] == "verified registry model" and info["version"] == "v-fixture" and info["is_fixture"] is True
    r = live.post("/pca-demo/predict", headers=auth(), json={"features": row(V3=3.0, V6=3.0, V9=3.0)})
    assert r.status_code == 200 and r.json()["model_version"] == "v-fixture" and r.json()["saved"] is False
    assert r.json()["prediction"] in (0, 1) and 0 <= r.json()["fraud_probability"] <= 1 and r.json()["risk_level"] in ("High", "Medium", "Low")
    bad = live.post("/pca-demo/predict", headers=auth(), json={"features": {"V1": 1.0}})
    assert bad.status_code == 422
