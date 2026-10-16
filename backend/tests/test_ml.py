import joblib
import numpy as np
import pandas as pd
import pytest

from app.ml import feature_schema as fs
from app.ml.predict import ModelUnavailable, Predictor
from app.ml.synthetic import generate
from app.ml.train_model import save_artifact, train


@pytest.fixture(scope="module")
def df():
    return generate(2000, seed=3)


def test_synthetic_dataset_is_valid_and_has_both_classes(df):
    assert fs.validate_dataframe(df) == []
    assert set(df[fs.TARGET].unique()) == {0, 1}


def test_missing_target_column(df):
    assert "Missing required columns" in fs.validate_dataframe(df.drop(columns=[fs.TARGET]))[0]


def test_invalid_labels(df):
    bad = df.copy()
    bad.loc[0, fs.TARGET] = 7
    assert any("only 0 and 1" in p for p in fs.validate_dataframe(bad))


def test_missing_values(df):
    bad = df.copy()
    bad.loc[0, "amount"] = None
    assert any("missing values" in p for p in fs.validate_dataframe(bad))


def test_out_of_range_and_unknown_category(df):
    bad = df.copy()
    bad.loc[0, "hour"] = 99
    bad.loc[1, "branch"] = "Atlantis"
    probs = fs.validate_dataframe(bad)
    assert any("hour" in p for p in probs) and any("unknown categories" in p for p in probs)


def test_train_rejects_invalid_data(df):
    with pytest.raises(ValueError, match="validation failed"):
        train(df.drop(columns=["amount"]), "x", True)


def test_train_rejects_tiny_class(df):
    tiny = df.copy()
    tiny[fs.TARGET] = 0
    tiny.loc[:4, fs.TARGET] = 1
    with pytest.raises(ValueError, match="at least 10"):
        train(tiny, "x", True)


def test_no_target_leakage_in_features():
    assert fs.TARGET not in fs.FEATURES


def test_training_is_reproducible(df):
    _, m1 = train(df, "x", True, n_estimators=20)
    _, m2 = train(df, "x", True, n_estimators=20)
    assert m1.metrics == m2.metrics


def test_metrics_cover_required_measures(df):
    _, meta = train(df, "x", True, n_estimators=20)
    for k in ("precision", "recall", "f1", "pr_auc", "roc_auc", "confusion_matrix", "test_rows"):
        assert k in meta.metrics
    assert meta.metrics["test_rows"] == 400   # 20% held out, never trained on


def test_save_load_predict_roundtrip(df, tmp_path):
    pipe, meta = train(df, "x", True, n_estimators=20)
    path = save_artifact(pipe, meta, tmp_path / "m.joblib")
    p = Predictor()
    p.load(path)
    assert p.available
    out = p.predict({"amount": 100.0, "hour": 12, "failed_attempts": 0, "new_device": 0, "international": 0,
                     "customer_avg_spend": 100.0, "payment_method": "Card", "branch": "Online"})
    assert 0.0 <= out.probability <= 1.0 and out.model_version == meta.version


def test_preprocessing_consistency(df, tmp_path):
    """Saved pipeline gives identical probabilities to the in-memory one (same preprocessing)."""
    pipe, meta = train(df, "x", True, n_estimators=20)
    path = save_artifact(pipe, meta, tmp_path / "m.joblib")
    loaded = joblib.load(path)["pipeline"]
    sample = df[fs.FEATURES].head(50)
    assert np.allclose(pipe.predict_proba(sample), loaded.predict_proba(sample), atol=1e-9)


def test_incompatible_schema_not_used(df, tmp_path):
    pipe, meta = train(df, "x", True, n_estimators=20)
    meta.schema_hash = "old-schema"
    path = save_artifact(pipe, meta, tmp_path / "old.joblib")
    p = Predictor()
    p.load(path)
    assert not p.available and "different feature schema" in p.error
    with pytest.raises(ModelUnavailable):
        p.predict({})


def test_corrupt_and_missing_model_files(tmp_path):
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a model")
    p = Predictor()
    p.load(bad)
    assert not p.available and "Could not read" in p.error
    p.load(tmp_path / "nope.joblib")
    assert not p.available and "not found" in p.error


def test_unknown_category_fails_loudly(df, tmp_path):
    pipe, meta = train(df, "x", True, n_estimators=20)
    p = Predictor()
    p.load(save_artifact(pipe, meta, tmp_path / "m.joblib"))
    with pytest.raises(Exception):
        p.predict({"amount": 1.0, "hour": 1, "failed_attempts": 0, "new_device": 0, "international": 0,
                   "customer_avg_spend": 1.0, "payment_method": "Cheque", "branch": "Online"})


def test_failed_save_leaves_no_artifact(df, tmp_path, monkeypatch):
    pipe, meta = train(df, "x", True, n_estimators=20)
    monkeypatch.setattr(pd.DataFrame, "__getitem__", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    target = tmp_path / "m.joblib"
    with pytest.raises(RuntimeError):
        save_artifact(pipe, meta, target)
    monkeypatch.undo()
    assert not target.exists() and list(tmp_path.glob("*.tmp")) == []


def test_risk_levels():
    p = Predictor(high=0.7, medium=0.3)
    assert [p.risk_level(x) for x in (0.0, 0.29, 0.3, 0.69, 0.7, 1.0)] == ["Low", "Low", "Medium", "Medium", "High", "High"]
