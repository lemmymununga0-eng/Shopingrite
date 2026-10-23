"""Grocery transaction schema, verified-label dataset, honest training refusal, and checkout -> assessment -> alert -> outcome.

IMPORTANT: models trained here use a small deterministic FIXTURE (`fixture_frame`), flagged is_fixture. They test the mechanics only;
no number here says anything about real fraud detection in this store."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Case, MlPrediction, Order, OrderOutcome
from app.factory import create_app
from app.ml import registry as reg
from app.ml import store_dataset as sd
from app.ml import store_schema as schema
from app.ml.framework import train_task
from app.ml.train_store import train_from_session
from tests.conftest import admin_h, auth, cust
from tests.test_store_risk import FRAUD, buy, midday  # noqa: F401  (autouse fixture)

GOOD = dict(total_cents=25_000, currency="ZMW", max_line_quantity=2, orders_last_hour=1, prior_orders=3, prior_paid_orders=2,
            average_paid_total_cents=18_000, failed_payments_24h=0, rejected_checkouts_10m=0, delivery_address_seen_before=True,
            fulfilment="delivery", local_hour=14, payment_method="card")


# ------------------------------------------------------------------------------------------------------------ schema
def test_a_complete_valid_row_passes_and_has_the_documented_shape():
    assert schema.validate(GOOD) is None
    row = schema.row(GOOD)
    assert list(row) == schema.FEATURE_NAMES and row["delivery_address_seen_before"] == 1 and "currency" not in row


@pytest.mark.parametrize("drop", schema.FEATURE_NAMES)
def test_every_missing_field_is_reported_not_filled(drop):
    f = {k: v for k, v in GOOD.items() if k != drop}
    r = schema.validate(f)
    assert r["status"] == "unsupported_input_schema" and r["missing_features"] == [drop]


def test_unexpected_and_sensitive_fields_are_refused():
    r = schema.validate({**GOOD, "card_number": "4111", "contact_email": "a@b.c", "user_id": "u1"})
    assert r["status"] == "unsupported_input_schema" and r["unexpected_features"] == ["card_number", "contact_email", "user_id"]


@pytest.mark.parametrize("bad", [{"total_cents": -5}, {"total_cents": 1.5}, {"total_cents": float("nan")}, {"local_hour": 24},
                                 {"payment_method": "bitcoin"}, {"fulfilment": "drone"}, {"delivery_address_seen_before": 1},
                                 {"failed_payments_24h": "2"}, {"orders_last_hour": True}])
def test_bad_values_are_invalid_input(bad):
    r = schema.validate({**GOOD, **bad})
    assert r["status"] == "invalid_input" and r["problems"]


def test_other_currencies_are_unsupported():
    assert schema.validate({**GOOD, "currency": "USD"})["status"] == "unsupported_input_schema"


def test_schema_documents_source_privacy_and_missing_handling_and_excludes_sensitive_data():
    for f in schema.document():
        assert f["source"] and f["privacy"] and f["missing"] and f["schema_version"] == "grocery_txn_v1"
    banned = ("password", "cvv", "card_number", "email", "phone", "address_line", "name", "token", "ip", "user_id")
    assert not [n for n in schema.FEATURE_NAMES if any(b == n or b in n.split("_") for b in banned)]


def test_the_features_the_store_really_stores_satisfy_the_schema(client):
    """Not a hand-written dict: the snapshot saved with a real checkout must validate."""
    o = buy(client, cust())
    with client.app.state.db.session() as s:
        from app.db.models import FraudAssessment
        a = s.scalar(select(FraudAssessment).where(FraudAssessment.order_id == o["id"]))
        assert schema.validate(json.loads(a.features_json)) is None


# ------------------------------------------------------------------------------------------------------------ labels
def _outcome(session, order_id, outcome, verified, reviewer="fraud-1"):
    session.add(OrderOutcome(order_id=order_id, outcome=outcome, verified=verified, reviewer_id=reviewer))


def test_only_verified_definite_outcomes_become_labels(client):
    ids = [buy(client, cust(f"c{i}"))["id"] for i in range(6)]
    with client.app.state.db.session() as s:
        _outcome(s, ids[0], "confirmed_fraud", True)
        _outcome(s, ids[1], "legitimate", True)
        _outcome(s, ids[2], "false_positive", True)
        _outcome(s, ids[3], "confirmed_fraud", False)       # suspicion, not verified: never a label
        _outcome(s, ids[4], "undetermined", True)           # verified but inconclusive: not a label
        # ids[5]: no outcome at all: not assumed legitimate
    with client.app.state.db.session() as s:
        df, counts = sd.labelled_rows(s)
    assert sorted(df["label"]) == [0, 0, 1] and set(df["order_id"]) == set(ids[:3])
    assert counts["excluded_unverified"] == 1 and counts["excluded_undetermined"] == 1 and counts["used"] == 3
    assert "user_id" in df.columns and not {"contact_email", "contact_name"} & set(df.columns)


def test_the_newest_outcome_wins_and_a_later_unverified_note_removes_the_label(client):
    oid = buy(client, cust("c1"))["id"]
    with client.app.state.db.session() as s:
        _outcome(s, oid, "confirmed_fraud", True)
        _outcome(s, oid, "legitimate", True)
    with client.app.state.db.session() as s:
        assert list(sd.labelled_rows(s)[0]["label"]) == [0]
        _outcome(s, oid, "legitimate", False)
    with client.app.state.db.session() as s:
        assert sd.labelled_rows(s)[0].empty


def test_features_are_the_snapshot_taken_at_placement_not_recomputed_later(client):
    oid = buy(client, cust("c1"))["id"]
    with client.app.state.db.session() as s:
        _outcome(s, oid, "legitimate", True)
        o = s.get(Order, oid)
        o.total_cents = 999_999                              # an edit after the fact must not leak into the training row
    with client.app.state.db.session() as s:
        assert sd.labelled_rows(s)[0].iloc[0]["total_cents"] != 999_999


def test_readiness_and_training_are_refused_without_enough_verified_labels(client):
    oid = buy(client, cust("c1"))["id"]
    with client.app.state.db.session() as s:
        _outcome(s, oid, "confirmed_fraud", True)
    with client.app.state.db.session() as s:
        r = sd.readiness(s)
        assert r["ready_to_train"] is False and r["verified_fraud"] == 1 and r["shortfall"]
        with pytest.raises(sd.InsufficientLabels):
            train_from_session(s, artifact_root=client.app.state.settings.ml_artifact_dir)
    assert reg.load_current("store_grocery", schema.FEATURE_NAMES, client.app.state.settings.ml_artifact_dir).state == reg.NOT_TRAINED


# ------------------------------------------------------------------------------------------------------------ fixture model
def fixture_frame(n=1500, seed=5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fraud = (rng.random(n) < 0.25).astype(int)
    users = rng.integers(0, 150, n)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        f = fraud[i]
        rows.append({"order_id": f"o{i}", "user_id": f"u{users[i]}", "created_at": base + timedelta(minutes=30 * i),
                     "total_cents": int(rng.lognormal(10.5 + 1.2 * f, 0.5)), "max_line_quantity": int(rng.integers(1, 4 + 8 * f)),
                     "orders_last_hour": int(rng.integers(0, 2 + 3 * f)), "prior_orders": int(rng.integers(0, 12 - 10 * f + 1)),
                     "prior_paid_orders": int(rng.integers(0, 6 - 5 * f + 1)), "average_paid_total_cents": int(rng.lognormal(10, 0.4)),
                     "failed_payments_24h": int(rng.integers(0, 1 + 3 * f)), "rejected_checkouts_10m": 0,
                     "delivery_address_seen_before": bool(rng.random() > 0.2 + 0.6 * f), "fulfilment": str(rng.choice(["delivery", "collection"])),
                     "local_hour": int(rng.integers(0, 24)), "payment_method": str(rng.choice(["card", "mtn_momo", "airtel_money", "cod"])), "label": int(f)})
    df = pd.DataFrame(rows)
    df["delivery_address_seen_before"] = df["delivery_address_seen_before"].astype(int)
    return df


SMALL = sd.Requirements(fraud=50, legitimate=200, customers=20)


@pytest.fixture(scope="module")
def trained_store():
    spec = sd.store_task(fixture_frame(), fast=True, is_fixture=True, req=SMALL)
    return train_task(spec, split_method="group", folds=3, log=lambda *a: None)


def test_store_training_uses_a_customer_grouped_split_and_records_the_policy(trained_store):
    m = trained_store.metadata
    assert m["split"]["method"].startswith("group-based") and m["split"]["overlap_checked"] is True
    assert m["input_features"] == schema.FEATURE_NAMES and m["is_fixture"] is True
    assert any("customer id" in e["name"] for e in m["excluded_features"])
    assert m["validation"]["passed"], m["validation"]["failures"]
    assert any("Selection bias" in x for x in m["limitations"])


def test_store_task_refuses_too_little_data_even_with_fixture_flag():
    with pytest.raises(sd.InsufficientLabels):
        sd.store_task(fixture_frame(n=120), is_fixture=True, req=SMALL)


def _promote(trained_store, root, experimental=True, version="v-store-fixture"):
    meta = json.loads(json.dumps(trained_store.metadata, default=str))
    meta.update(version=version, experimental=experimental, schema_version=schema.SCHEMA_VERSION)
    reg.save_version("store_grocery", version, trained_store.pipeline, meta, "report", None, root)
    reg.promote("store_grocery", version, root)


def test_a_fixture_store_model_scores_a_real_checkout_in_shadow_mode_without_alerting(settings, trained_store):
    _promote(trained_store, settings.ml_artifact_dir, experimental=True)
    with TestClient(create_app(settings)) as c:
        o = buy(c, cust())
        with c.app.state.db.session() as s:
            p = s.scalar(select(MlPrediction).where(MlPrediction.order_id == o["id"], MlPrediction.model == "store_grocery"))
            assert p.status == "ok" and p.experimental is True and 0 <= p.probability <= 1 and p.model_version == "v-store-fixture"
            assert s.scalar(select(Case).where(Case.source_type == "order_anomaly", Case.source_record_id == o["id"])) is None
        d = c.get(f"/staff/orders/{o['id']}", headers=FRAUD).json()
        sg = next(m for m in d["ml_predictions"] if m["model"] == "store_grocery")
        assert sg["experimental"] is True and sg["event_id"].startswith(o["id"])
        st = c.get("/fraud/model-status", headers=FRAUD).json()["store_scoring"]
        assert st["method"].startswith("supervised model (experimental")


def test_a_non_experimental_flagged_prediction_opens_a_case_but_an_unflagged_one_does_not(settings, trained_store, monkeypatch):
    _promote(trained_store, settings.ml_artifact_dir, experimental=False)
    with TestClient(create_app(settings)) as c:
        svc = c.app.state.ml
        real = svc.predict
        monkeypatch.setattr(svc, "predict", lambda name, f: {**real(name, f), "flagged": True} if name == "store_grocery" else real(name, f))
        flagged = buy(c, cust("c-a"))
        monkeypatch.setattr(svc, "predict", lambda name, f: {**real(name, f), "flagged": False} if name == "store_grocery" else real(name, f))
        calm = buy(c, cust("c-b"))
        with c.app.state.db.session() as s:
            assert s.scalar(select(Case).where(Case.source_record_id == flagged["id"])) is not None
            assert s.scalar(select(Case).where(Case.source_record_id == calm["id"])) is None


def test_a_model_trained_on_another_schema_version_is_refused(settings, trained_store):
    meta = json.loads(json.dumps(trained_store.metadata, default=str))
    meta.update(version="v-old", experimental=True, schema_version="grocery_txn_v0")
    meta["input_features"] = ["total_cents"]
    reg.save_version("store_grocery", "v-old", trained_store.pipeline, meta, "", None, settings.ml_artifact_dir)
    reg.promote("store_grocery", "v-old", settings.ml_artifact_dir)
    with TestClient(create_app(settings)) as c:
        sg = next(m for m in c.get("/fraud/model-status", headers=FRAUD).json()["models"] if m["model"] == "store_grocery")
        assert sg["ready"] is False and sg["state"] == "schema_incompatible"
        assert c.post("/fraud/predict", headers=FRAUD, json={"model": "store_grocery", "features": GOOD}).status_code == 503


def test_predict_endpoint_validates_store_features(settings, trained_store):
    _promote(trained_store, settings.ml_artifact_dir)
    with TestClient(create_app(settings)) as c:
        ok = c.post("/fraud/predict", headers=FRAUD, json={"model": "store_grocery", "features": GOOD})
        assert ok.status_code == 200 and ok.json()["experimental"] is True and ok.json()["saved"] is False
        bad = c.post("/fraud/predict", headers=FRAUD, json={"model": "store_grocery", "features": {**GOOD, "payment_method": "bitcoin"}})
        assert bad.status_code == 422 and bad.json()["detail"]["status"] == "invalid_input"
        gone = {k: v for k, v in GOOD.items() if k != "local_hour"}
        assert c.post("/fraud/predict", headers=FRAUD, json={"model": "store_grocery", "features": gone}).json()["detail"]["missing_features"] == ["local_hour"]
        assert c.post("/fraud/predict", headers=cust(), json={"model": "store_grocery", "features": GOOD}).status_code == 403


def test_schema_endpoint_is_staff_only(client):
    assert client.get("/fraud/store-schema", headers=FRAUD).json()["schema_version"] == "grocery_txn_v1"
    assert client.get("/fraud/store-schema", headers=cust()).status_code == 403


# ------------------------------------------------------------------------------------------------------------ end to end
from app.db.models import FraudAssessment, PaymentAttempt  # noqa: E402
from tests.conftest import order_body, put_in_cart  # noqa: E402


def test_checkout_to_console_end_to_end(settings):
    """Customer checks out (simulated payment) -> order + payment attempt -> assessment (method rules) + model records ->
    case for a high-value order -> staff see it -> analyst records a verified outcome -> it becomes a label; customers see none of it."""
    settings.order_high_value_cents = 100                      # make this basket a "review" order
    with TestClient(create_app(settings)) as c:
        h = cust("shopper-1")
        put_in_cart(c, h, "DEMO-FP-001", 1)
        body = order_body(fulfilment="collection", payment={"method": "simulated", "scenario": "success"})
        body.pop("address", None)
        key = {"Idempotency-Key": "e2e-key-0001"}
        first = c.post("/orders", json=body, headers={**h, **key})
        assert first.status_code == 201, first.text
        order = first.json()
        again = c.post("/orders", json=body, headers={**h, **key})                      # network retry / double click
        assert again.json()["id"] == order["id"]
        with c.app.state.db.session() as s:
            assert s.query(Order).count() == 1
            assert s.query(PaymentAttempt).filter_by(order_id=order["id"]).count() == 1
            a = s.scalars(select(FraudAssessment).where(FraudAssessment.order_id == order["id"])).all()
            assert len(a) == 1 and a[0].engine == "store_risk" and a[0].decision == "review"           # rules, labelled as such
            ml = s.scalars(select(MlPrediction).where(MlPrediction.order_id == order["id"])).all()
            assert len(ml) == 2 and all(m.probability is None for m in ml)                             # nothing trained: no invented score
            case = s.scalar(select(Case).where(Case.source_record_id == order["id"]))
            assert case is not None and case.source_type == "order_anomaly"
        # payment outcome is separate from risk: the order is paid AND still flagged for review
        assert c.get(f"/orders/{order['id']}", headers=h).json()["payment_status"] in ("paid", "pending", "cod_due")
        staff = c.get(f"/staff/orders/{order['id']}", headers=FRAUD).json()
        assert staff["assessments"][0]["decision"] == "review" and staff["assessments"][0]["engine"] == "store_risk_v1"
        assert {m["model"] for m in staff["ml_predictions"]} == {"store_grocery", "creditcard_pca"} and staff["case"]
        # access separation
        other = cust("shopper-2")
        assert c.get(f"/orders/{order['id']}", headers=other).status_code == 404
        for path in (f"/staff/orders/{order['id']}", f"/staff/orders/{order['id']}/outcome", "/fraud/model-status", "/staff/ml-summary"):
            assert c.get(path, headers=h).status_code == 403
        assert "risk" not in json.dumps(c.get(f"/orders/{order['id']}", headers=h).json()).lower()
        # a suspicion is not a label; a verified conclusion is
        assert c.post(f"/staff/orders/{order['id']}/outcome", headers=FRAUD, json={"outcome": "confirmed_fraud"}).status_code == 201
        with c.app.state.db.session() as s:
            assert sd.labelled_rows(s)[0].empty
        assert c.post(f"/staff/orders/{order['id']}/outcome", headers=FRAUD,
                      json={"outcome": "confirmed_fraud", "verified": True, "note": "chargeback"}).status_code == 201
        with c.app.state.db.session() as s:
            df, _ = sd.labelled_rows(s)
            assert list(df["label"]) == [1] and df.iloc[0]["total_cents"] == order["total_cents"]
        assert c.get("/fraud/model-status", headers=FRAUD).json()["store_scoring"]["labels"]["verified_fraud"] == 1


# ------------------------------------------------------------------------------------------------------------ rules baseline, audit queue
def test_rules_baseline_scores_the_same_held_out_customers_as_training():
    df = fixture_frame()
    rng = np.random.default_rng(1)
    df["rules_score"] = (df["label"] * 30 + rng.integers(0, 60, len(df))).astype(int)        # a mediocre rule engine
    df["rules_decision"] = np.where(df["rules_score"] >= 30, "review", "allow")
    rb = sd.rules_baseline(df)
    spec = sd.store_task(df, fast=True, is_fixture=True, req=SMALL)
    result = train_task(spec, split_method="group", folds=3, log=lambda *a: None)
    assert rb["test_rows"] == result.metadata["split"]["test_rows"] and rb["test_fraud"] == result.metadata["split"]["test_class_counts"]["fraud"]
    assert 0 < rb["pr_auc"] < 1


def test_a_model_that_does_not_beat_the_rules_is_not_promoted(tmp_path):
    from app.ml.train import run
    df = fixture_frame()
    df["rules_score"] = df["label"] * 100                                                        # rules that are perfect: nothing can beat them
    df["rules_decision"] = np.where(df["label"] == 1, "high", "allow")
    spec = sd.store_task(df, fast=True, is_fixture=True, req=SMALL)
    out = run("store-grocery", fast=False, spec=spec, artifact_root=tmp_path, folds=3, log=lambda *a: None, split_method="group",
              meta_extra={"rules_baseline": sd.rules_baseline(df)})
    assert out["promoted"] is False and any("does not beat the rule engine" in f for f in out["failures"])


def test_label_queue_lists_flagged_orders_first_and_a_stable_audit_sample_of_unflagged_ones(settings):
    settings.order_high_value_cents = 100
    with TestClient(create_app(settings)) as c:
        flagged = buy(c, cust("q-1"))
        from app.routers.staff_orders import AUDIT_SAMPLE_RATE
        assert AUDIT_SAMPLE_RATE == 10
        q = c.get("/staff/label-queue", headers=FRAUD).json()
        assert q["items"][0]["order_id"] == flagged["id"] and q["items"][0]["why"] == "flagged by rules"
        assert c.get("/staff/label-queue", headers=cust()).status_code == 403
        assert c.get("/staff/label-queue", headers=FRAUD).json() == q                               # deterministic: same answer twice
        c.post(f"/staff/orders/{flagged['id']}/outcome", headers=FRAUD, json={"outcome": "legitimate", "verified": True})
        assert flagged["id"] not in [i["order_id"] for i in c.get("/staff/label-queue", headers=FRAUD).json()["items"]]


def test_readiness_counts_labels_that_come_from_unflagged_orders(client):
    oid = buy(client, cust("c1"))["id"]                                                              # ordinary order: rules say allow
    with client.app.state.db.session() as s:
        _outcome(s, oid, "legitimate", True)
    with client.app.state.db.session() as s:
        assert sd.readiness(s)["verified_from_unflagged_orders"] == 1
