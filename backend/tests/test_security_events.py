"""Security Monitor: events, correlation ids, filters, thresholds, redaction."""
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.security import redact, redact_text
from app.factory import create_app

from .conftest import SECRET, admin_h, auth, cust, valid_payload


def SEC():
    return auth("sec-1", "security_analyst")


def events(client, qs=""):
    return client.get(f"/security/events{qs}", headers=SEC()).json()


def test_auth_failures_are_recorded_with_correlation_id(client):
    r = client.get("/cart", headers={"Authorization": "Bearer not.a.token", "X-Request-ID": "trace-abcdef-0001"})
    assert r.status_code == 401 and r.headers["x-request-id"] == "trace-abcdef-0001"
    ev = events(client, "?correlation_id=trace-abcdef-0001")
    assert ev["total"] == 1 and ev["items"][0]["event_type"] == "auth.invalid_token"
    assert ev["items"][0]["category"] == "authentication" and ev["items"][0]["path"] == "/cart"
    assert "not.a.token" not in json.dumps(ev)


def test_missing_and_expired_tokens_are_distinguished(client):
    client.get("/cart")
    expired = jwt.encode({"sub": "u", "aud": "authenticated", "exp": 1}, SECRET, algorithm="HS256")
    client.get("/cart", headers={"Authorization": f"Bearer {expired}"})
    types = {e["event_type"] for e in events(client)["items"]}
    assert {"auth.missing_token", "auth.token_expired"} <= types


def test_authorization_failures_recorded_with_actor(client):
    client.get("/security/events", headers=cust("mallory"))
    e = events(client, "?category=authorization")["items"]
    assert e and e[0]["actor_id"] == "mallory" and e[0]["status_code"] == 403
    assert "denied" in e[0]["message"].lower()


def test_validation_rejections_recorded_without_values(client):
    client.post("/predict", json=valid_payload(amount=-5, transaction_reference="SECRET-ref-123"),
                headers=auth("f", "fraud_analyst"))
    e = events(client, "?category=input")["items"]
    assert e and e[0]["event_type"] == "input.rejected"
    assert "SECRET-ref-123" not in json.dumps(e)


def test_rate_limit_events(settings):
    settings.predict_rate_limit_per_min = 1
    with TestClient(create_app(settings)) as c:
        h = auth("f", "fraud_analyst")
        for _ in range(3):
            c.post("/predict", json=valid_payload(), headers=h)
        ev = c.get("/security/events?category=rate_limit", headers=SEC()).json()
        assert ev["total"] >= 1 and ev["items"][0]["event_type"] == "rate_limit.exceeded"


def test_model_unavailable_is_an_event(client_no_model):
    client_no_model.post("/predict", json=valid_payload(), headers=auth("f", "fraud_analyst"))
    ev = client_no_model.get("/security/events?category=model", headers=SEC()).json()
    assert ev["total"] == 1 and ev["items"][0]["severity"] == "high"


def test_unhandled_exception_is_an_event_with_correlation_id(client, monkeypatch):
    from app.services import inventory_service
    monkeypatch.setattr(inventory_service, "list_categories",
                        lambda s: (_ for _ in ()).throw(RuntimeError("db exploded password=hunter2")))
    with TestClient(client.app, raise_server_exceptions=False) as c:
        r = c.get("/categories")
    assert r.status_code == 500 and r.json()["detail"] == "Internal server error"
    cid = r.json()["correlation_id"]
    assert cid == r.headers["x-request-id"] and "hunter2" not in r.text
    ev = events(client, f"?correlation_id={cid}")
    assert ev["total"] == 1 and ev["items"][0]["category"] == "application"
    assert "hunter2" not in json.dumps(ev)


def test_body_too_large_is_an_event(client):
    client.post("/predict", content=b"x" * 30000,
                headers={**auth("f", "fraud_analyst"), "Content-Type": "application/json"})
    assert events(client, "?category=input")["items"][0]["event_type"] == "input.body_too_large"


def test_event_list_filters_search_pagination_detail(client):
    for i in range(6):
        client.get("/cart", headers={"Authorization": f"Bearer bad{i}.x.y", "X-Request-ID": f"trace-filter-{i:04d}"})
        client.get("/security/events", headers=cust(f"c{i}"))
    allv = events(client, "?page_size=100")
    assert allv["total"] >= 6
    assert all(e["severity"] == "medium" for e in events(client, "?severity=medium&page_size=100")["items"])
    assert len(events(client, "?category=authentication&page_size=3")["items"]) >= 1   # identical repeats within 5 s collapse
    assert events(client, "?search=invalid%20access")["total"] >= 1
    page2 = events(client, "?page=2&page_size=2")
    assert page2["page"] == 2 and len(page2["items"]) == 2
    assert client.get("/security/events?severity=bogus", headers=SEC()).status_code == 422
    assert client.get("/security/events?category=bogus", headers=SEC()).status_code == 422
    assert client.get("/security/events?date_from=2026-02-30", headers=SEC()).status_code == 422
    assert events(client, "?date_from=2999-01-01")["total"] == 0
    one = allv["items"][0]
    d = client.get(f"/security/events/{one['id']}", headers=SEC()).json()
    assert d["id"] == one["id"] and "details" in d
    assert client.get("/security/events/999999", headers=SEC()).status_code == 404


def test_summary_counts(client):
    client.get("/cart")
    d = client.get("/security/summary", headers=SEC()).json()
    assert d["total"] >= 1 and d["by_category"]["authentication"] >= 1 and "not network" in d["scope_note"].lower()


def test_threshold_alert_creates_one_event_and_one_case(settings):
    with TestClient(create_app(settings)) as c:
        c.put("/security/thresholds", json={"values": {"auth_failures_per_10min": 3}}, headers=admin_h())
        ev = c.app.state.events
        for _ in range(6):
            ev.record("medium", "authentication", "auth.invalid_token", "Invalid token", client_tag="abc123")
        alerts = c.get("/security/events?category=threshold", headers=SEC()).json()
        assert alerts["total"] == 1 and alerts["items"][0]["severity"] == "high"       # one alert, not one per event
        cases = c.get("/investigations?source_type=security_alert", headers=SEC()).json()
        assert cases["total"] == 1 and "threshold" in cases["items"][0]["summary"].lower()


def test_thresholds_view_and_edit_permissions(client):
    assert client.get("/security/thresholds", headers=SEC()).json()["thresholds"]["auth_failures_per_10min"] == 10
    body = {"values": {"auth_failures_per_10min": 5}}
    assert client.put("/security/thresholds", json=body, headers=SEC()).status_code == 403
    assert client.put("/security/thresholds", json=body, headers=admin_h()).status_code == 200
    assert client.get("/security/thresholds", headers=SEC()).json()["thresholds"]["auth_failures_per_10min"] == 5
    assert client.put("/security/thresholds", json={"values": {"nope": 5}}, headers=admin_h()).status_code == 422
    assert client.put("/security/thresholds", json={"values": {"auth_failures_per_10min": 0}},
                      headers=admin_h()).status_code == 422
    assert client.get("/audit?action=settings.thresholds_changed", headers=SEC()).json()["total"] == 1
    assert events(client, "?category=privileged")["total"] == 1


def test_recording_failure_never_breaks_the_request(client, monkeypatch):
    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(client.app.state.db, "session", broken)
    assert client.app.state.events.record("low", "input", "x.y", "message") is None


# ---------------- redaction ----------------
def test_redact_removes_secrets_tokens_and_card_numbers():
    out = redact({"Authorization": "Bearer abc.def.ghi", "password": "pw", "api_key": "k",
                  "note": "card 4111 1111 1111 1111 ok", "nested": {"token": "t", "safe": "visible"},
                  "list": [{"secret": "s"}]})
    s = json.dumps(out)
    for leaked in ("abc.def.ghi", '"pw"', "4111", '"t"', '"s"'):
        assert leaked not in s
    assert out["nested"]["safe"] == "visible"


@pytest.mark.parametrize("text", ["Bearer eyJabcdefgh.eyJabcdefgh.sig", "GET /x?key=AIzaSyABC123&a=1",
                                  "token eyJhbGciOi123456.abcdefghij1.xyzxyzxyz"])
def test_redact_text_scrubs_credentials(text):
    out = redact_text(text)
    assert "AIzaSyABC123" not in out and "eyJabcdefgh" not in out and "eyJhbGciOi123456" not in out


def test_redact_limits_length_and_depth():
    assert len(redact_text("a" * 5000)) == 500
    deep = cur = {}
    for _ in range(20):
        cur["x"] = {}
        cur = cur["x"]
    assert "[REDACTED]" in json.dumps(redact(deep))
