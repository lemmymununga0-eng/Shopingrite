"""PCA-demo API endpoints (the payment /predict endpoint is covered in test_api.py)."""
import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.ml import pca_demo

from .conftest import auth
from .test_training import pca_fixture


@pytest.fixture(scope="module")
def pca_model_path(tmp_path_factory):
    pipe, meta = pca_demo.train(pca_fixture(), "fixture", n_estimators=30)
    return pca_demo.save(pipe, meta, tmp_path_factory.mktemp("pca") / "pca.joblib")


@pytest.fixture()
def pclient(settings, pca_model_path):
    settings.pca_model_path = pca_model_path
    with TestClient(create_app(settings)) as c:
        yield c


ROW = {f: 0.0 for f in pca_demo.FEATURES}


def test_requires_auth(pclient):
    assert pclient.get("/pca-demo/info").status_code == 401
    assert pclient.post("/pca-demo/predict", json={"features": ROW}).status_code == 401


def test_info_is_labelled_and_has_metrics(pclient):
    d = pclient.get("/pca-demo/info", headers=auth()).json()
    assert d["trained"] and "separate from the payment form" in d["label"] and "pr_auc" in d["metrics"]


def test_valid_prediction_is_not_saved(pclient):
    r = pclient.post("/pca-demo/predict", json={"features": ROW}, headers=auth())
    assert r.status_code == 200
    d = r.json()
    assert 0 <= d["fraud_probability"] <= 1 and d["risk_level"] in {"Low", "Medium", "High"} and d["saved"] is False
    assert pclient.get("/transactions", headers=auth()).json()["total"] == 0


def test_fraud_like_row_scores_higher_than_normal_row(pclient):
    normal = pclient.post("/pca-demo/predict", json={"features": ROW}, headers=auth()).json()["fraud_probability"]
    risky = pclient.post("/pca-demo/predict", json={"features": {**ROW, "V1": 3.5, "V2": 3.5, "V3": 3.5}}, headers=auth()).json()["fraud_probability"]
    assert risky > normal


def test_missing_and_extra_features_rejected(pclient):
    short = {k: v for k, v in ROW.items() if k != "V7"}
    r = pclient.post("/pca-demo/predict", json={"features": short}, headers=auth())
    assert r.status_code == 422 and r.json()["detail"]["missing_features"] == ["V7"]
    r = pclient.post("/pca-demo/predict", json={"features": {**ROW, "hour": 3}}, headers=auth())
    assert r.status_code == 422 and r.json()["detail"]["unexpected_features"] == ["hour"]


def test_non_numeric_and_nan_rejected(pclient):
    assert pclient.post("/pca-demo/predict", json={"features": {**ROW, "V1": "abc"}}, headers=auth()).status_code == 422
    r = pclient.post("/pca-demo/predict", content='{"features": {"V1": NaN}}',
                     headers={**auth(), "Content-Type": "application/json"})
    assert r.status_code == 422


def test_unavailable_model_returns_503(settings, tmp_path):
    settings.pca_model_path = tmp_path / "none.joblib"
    with TestClient(create_app(settings)) as c:
        assert c.get("/pca-demo/info", headers=auth()).json()["trained"] is False
        r = c.post("/pca-demo/predict", json={"features": ROW}, headers=auth())
        assert r.status_code == 503 and "unavailable" in r.json()["detail"].lower()


def test_wrong_feature_list_model_refused(settings, tmp_path):
    import joblib
    pipe, meta = pca_demo.train(pca_fixture(), "f", n_estimators=10)
    meta["features"] = meta["features"][:-1]
    bad = tmp_path / "bad.joblib"
    joblib.dump({"pipeline": pipe, "metadata": meta}, bad)
    p = pca_demo.PcaPredictor()
    p.load(bad)
    assert not p.available and "different feature list" in p.error
