"""Dataset loading/inspection and PCA-demo training tests. The PCA data below is a tiny generated TEST FIXTURE,
not the Kaggle dataset, and no score from it means anything about real fraud."""
import json

import numpy as np
import pandas as pd
import pytest

import inspect_dataset
from app.ml import dataset_report as dr
from app.ml import pca_demo


def pca_fixture(n=600, fraud=60, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(rng.normal(size=(n, 28)), columns=[f"V{i}" for i in range(1, 29)])
    df.insert(0, "Time", np.arange(n, dtype=float))
    df["Amount"] = rng.gamma(2.0, 30.0, n).round(2)
    df["Class"] = 0
    df.loc[:fraud - 1, "Class"] = 1
    df.loc[:fraud - 1, ["V1", "V2", "V3"]] += 3.0            # separable on purpose, so the tiny model can learn
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


@pytest.fixture()
def csv_path(tmp_path):
    p = tmp_path / "creditcard.csv"
    pca_fixture().to_csv(p, index=False)
    return p


# ---------- file loading ----------
def test_missing_file(tmp_path):
    with pytest.raises(dr.DatasetFileError, match="not found"):
        dr.load_csv(tmp_path / "nope.csv")


def test_wrong_extension(tmp_path):
    p = tmp_path / "data.txt"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(dr.DatasetFileError, match=".csv"):
        dr.load_csv(p)


def test_empty_and_header_only_files(tmp_path):
    e = tmp_path / "e.csv"
    e.write_text("")
    with pytest.raises(dr.DatasetFileError, match="empty"):
        dr.load_csv(e)
    h = tmp_path / "h.csv"
    h.write_text("Time,Amount,Class\n")
    with pytest.raises(dr.DatasetFileError):
        dr.load_csv(h)


# ---------- inspection ----------
def test_inspect_valid_pca_file(csv_path):
    r = dr.inspect(csv_path)
    assert r["detected_schema"] == "pca" and r["rows"] == 600 and r["columns"] == 31
    assert r["legitimate"] == 540 and r["fraud"] == 60 and r["fraud_percent"] == 10.0
    assert r["training_ready"] and r["problems"] == []


def test_inspect_missing_target_column(tmp_path):
    p = tmp_path / "d.csv"
    pca_fixture().drop(columns=["Class"]).to_csv(p, index=False)
    r = dr.inspect(p)
    assert not r["training_ready"] and any("Target column" in x for x in r["problems"])


def test_inspect_custom_target_name(tmp_path):
    p = tmp_path / "d.csv"
    pca_fixture().rename(columns={"Class": "label"}).to_csv(p, index=False)
    assert dr.inspect(p, target="label")["training_ready"]


def test_inspect_invalid_labels_missing_and_duplicates(tmp_path):
    df = pca_fixture()
    df.loc[0, "Class"] = 2
    df.loc[1, "V5"] = np.nan
    df = pd.concat([df, df.iloc[[5]]])
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    r = dr.inspect(p)
    assert any("only 0 and 1" in x for x in r["problems"]) and r["missing_per_column"]["V5"] == 1 and r["duplicate_rows"] >= 1


def test_inspect_unknown_schema(tmp_path):
    p = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(p, index=False)
    r = dr.inspect(p)
    assert r["detected_schema"] == "unknown" and not r["training_ready"]


def test_inspect_script_writes_reports_and_sets_exit_code(csv_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(inspect_dataset, "HERE", tmp_path)
    assert inspect_dataset.main([str(csv_path)]) == 0
    assert json.loads((tmp_path / "reports" / "dataset_report.json").read_text())["rows"] == 600
    assert inspect_dataset.main([str(tmp_path / "missing.csv")]) == 1
    assert "ERROR" in capsys.readouterr().out


# ---------- PCA training ----------
def test_pca_validate_rejects_bad_data():
    with pytest.raises(pca_demo.DatasetError, match="Missing required columns"):
        pca_demo.validate(pca_fixture().drop(columns=["V9"]))
    bad = pca_fixture()
    bad.loc[0, "Class"] = 5
    with pytest.raises(pca_demo.DatasetError, match="only 0 and 1"):
        pca_demo.validate(bad)
    text = pca_fixture().astype({"V1": object})
    text.loc[0, "V1"] = "abc"
    with pytest.raises(pca_demo.DatasetError, match="non-numeric"):
        pca_demo.validate(text)


def test_cleaning_is_reported_not_silent():
    df = pca_fixture()
    df = pd.concat([df, df.iloc[:5]])                       # 5 exact duplicates
    df.loc[df.index[10], "V2"] = np.inf
    cleaned, rep = pca_demo.clean(df)
    assert rep["dropped_duplicate_rows"] == 5 and rep["dropped_missing_or_infinite_rows"] == 1
    assert rep["rows_after_cleaning"] == len(cleaned) == 599     # 600 + 5 duplicates - 5 - 1 infinite


def test_pca_training_split_metrics_and_roundtrip(tmp_path):
    pipe, meta = pca_demo.train(pca_fixture(), "fixture", n_estimators=40)
    m = meta["metrics"]
    assert m["test_rows"] == 120 and m["support_fraud"] == 12 and m["support_legitimate"] == 108   # 20% held out
    for k in ("accuracy", "precision", "recall", "f1", "pr_auc", "roc_auc", "classification_report", "confusion_matrix"):
        assert k in m
    assert meta["split"]["stratified"] and meta["features"] == pca_demo.FEATURES and meta["version"].startswith("pca-")
    path = pca_demo.save(pipe, meta, tmp_path / "pca.joblib")
    p = pca_demo.PcaPredictor()
    p.load(path)
    assert p.available
    out = p.predict({f: 0.0 for f in pca_demo.FEATURES})
    assert 0 <= out["fraud_probability"] <= 1 and out["prediction"] in (0, 1) and out["model_version"] == meta["version"]


def test_pca_training_is_reproducible():
    _, a = pca_demo.train(pca_fixture(), "f", n_estimators=20)
    _, b = pca_demo.train(pca_fixture(), "f", n_estimators=20)
    assert a["metrics"]["confusion_matrix"] == b["metrics"]["confusion_matrix"]


def test_train_rejects_tiny_class():
    df = pca_fixture(n=200, fraud=5)
    with pytest.raises(pca_demo.DatasetError, match="at least 10"):
        pca_demo.train(df, "f")


def test_single_class_test_set_metrics_do_not_crash():
    from app.ml.evaluation import evaluate
    r = evaluate([0, 0, 0, 0], [0.1, 0.2, 0.1, 0.0], 0.5)
    assert r["roc_auc"] is None and "only one class" in r["warning"]


def test_failed_save_keeps_existing_model(tmp_path, monkeypatch):
    pipe, meta = pca_demo.train(pca_fixture(), "f", n_estimators=20)
    path = pca_demo.save(pipe, meta, tmp_path / "pca.joblib")
    before = path.read_bytes()
    monkeypatch.setattr(pca_demo.joblib, "load", lambda *_: (_ for _ in ()).throw(RuntimeError("corrupt")))
    with pytest.raises(RuntimeError):
        pca_demo.save(pipe, meta, path)
    assert path.read_bytes() == before and not list(tmp_path.glob("*.tmp"))


def test_cli_missing_dataset_message(tmp_path, capsys, monkeypatch):
    from app.ml import train_model as tm
    monkeypatch.setattr(tm, "DATA_DIR", tmp_path)
    assert tm.main(["--schema", "pca"]) == 1
    out = capsys.readouterr().out
    assert "kaggle.com/datasets/mlg-ulb/creditcardfraud" in out
    assert tm.main(["--schema", "pca", "--synthetic"]) == 1       # no synthetic fallback for the PCA model


def test_cli_trains_pca_from_csv(csv_path, tmp_path, monkeypatch):
    from app.ml import train_model as tm
    monkeypatch.setattr(tm, "REPORTS_DIR", tmp_path / "reports")
    assert tm.main(["--schema", "pca", "--csv", str(csv_path), "--out", str(tmp_path / "m.joblib")]) == 0
    assert (tmp_path / "m.joblib").exists() and (tmp_path / "reports" / "pca_demo_training_report.json").exists()


def test_payment_metrics_include_new_fields():
    from app.ml.synthetic import generate
    from app.ml.train_model import train
    _, meta = train(generate(1500, seed=2), "x", True, n_estimators=20)
    assert {"accuracy", "classification_report", "support_fraud", "threshold"} <= set(meta.metrics)
