"""Store integration of the models: honest unsupported_input_schema records, idempotency, alert policy, outcomes, isolation."""
import json

from sqlalchemy import func, select

from app.db.models import Case, MlPrediction, OrderOutcome
from app.services import order_risk

from .conftest import admin_h, auth, cust
from .test_store_risk import FRAUD, buy, midday  # noqa: F401  (midday is an autouse fixture)


def rows(client, order_id):
    with client.app.state.db.session() as s:
        return [(r.model, r.status, r.probability, json.loads(r.missing_features_json), r.trigger)
                for r in s.scalars(select(MlPrediction).where(MlPrediction.order_id == order_id).order_by(MlPrediction.id))]


def test_store_orders_record_an_honest_unsupported_result_without_a_score(client):
    o = buy(client, cust())
    got = rows(client, o["id"])
    assert {m for m, *_ in got} == {"store_grocery", "creditcard_pca"}
    # nothing is trained in this test environment, so no model may produce a number
    assert all(status == "model_unavailable" and prob is None for _, status, prob, _, _ in got)
    with client.app.state.db.session() as s:
        assert s.scalar(select(Case).where(Case.source_type == "order_anomaly")) is None


def test_reassessing_the_same_event_does_not_duplicate_predictions(client):
    o = buy(client, cust())
    s = client.app.state
    for _ in range(3):
        order_risk.evaluate(s.db, s.events, s.settings, o["id"], None, trigger="order_placed")
    assert len(rows(client, o["id"])) == 2                       # one per model, not three times that


def test_unsupported_store_features_are_reported_when_a_model_is_loaded(client):
    """With a model that is ready, store fields still cannot satisfy its schema: missing names are recorded, no score."""
    class Ready:
        def predict(self, name, features):
            return {"model": name, "status": "unsupported_input_schema", "missing_features": ["V1", "V2"],
                    "unexpected_features": sorted(features), "required_features": ["V1", "V2"]}
    client.app.state.db.ml = Ready()
    o = buy(client, cust(), qty=2)
    got = rows(client, o["id"])
    assert all(status == "unsupported_input_schema" and prob is None and missing == ["V1", "V2"] for _, status, prob, missing, _ in got)


def test_only_a_genuine_flagged_prediction_creates_an_alert(client):
    class Flagging:
        def predict(self, name, features):
            return {"model": name, "status": "ok", "model_version": "v-test", "probability": 0.97, "threshold": 0.5, "flagged": True}
    client.app.state.db.ml = Flagging()
    o = buy(client, cust())
    with client.app.state.db.session() as s:
        case = s.scalar(select(Case).where(Case.source_type == "order_anomaly", Case.source_record_id == o["id"]))
        assert case is not None


def test_staff_see_ml_status_and_customers_do_not(client):
    o = buy(client, cust())
    d = client.get(f"/staff/orders/{o['id']}", headers=FRAUD).json()
    assert len(d["ml_predictions"]) == 2 and d["ml_predictions"][0]["probability"] is None
    assert "ml_predictions" not in json.dumps(client.get(f"/orders/{o['id']}", headers=cust()).json())
    assert client.get(f"/staff/orders/{o['id']}", headers=cust()).status_code == 403


def test_outcomes_are_append_only_audited_and_permissioned(client):
    o = buy(client, cust())
    url = f"/staff/orders/{o['id']}/outcome"
    assert client.post(url, headers=cust(), json={"outcome": "legitimate"}).status_code == 403
    assert client.post(url, headers=FRAUD, json={"outcome": "bogus"}).status_code == 422
    assert client.post(url, headers=FRAUD, json={"outcome": "legitimate", "unknown": 1}).status_code == 422
    assert client.post(url, headers=FRAUD, json={"outcome": "undetermined", "note": "calling customer"}).status_code == 201
    r = client.post(url, headers=FRAUD, json={"outcome": "confirmed_fraud", "verified": True, "note": "chargeback"})
    assert r.status_code == 201 and r.json()["verified"] is True
    got = client.get(url, headers=FRAUD).json()["outcomes"]
    assert [x["outcome"] for x in got] == ["confirmed_fraud", "undetermined"]            # newest first, nothing overwritten
    assert client.post("/staff/orders/not-a-uuid/outcome", headers=FRAUD, json={"outcome": "legitimate"}).status_code == 404
    summary = client.get("/staff/ml-summary", headers=FRAUD).json()
    assert summary["verified_outcome_counts"] == {"confirmed_fraud": 1}
    with client.app.state.db.session() as s:
        assert s.scalar(select(func.count()).select_from(OrderOutcome)) == 2
    assert client.get("/staff/ml-summary", headers=cust()).status_code == 403
