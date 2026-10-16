import pytest

from .conftest import RISKY, auth, make_token, valid_payload


# ---------- system ----------
def test_health_reports_model(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["model_loaded"] is True and r.json()["mode"] == "REAL_MODEL"


def test_health_without_model(client_no_model):
    r = client_no_model.get("/health")
    assert r.status_code == 200 and r.json()["model_loaded"] is False and r.json()["mode"] == "MODEL_UNAVAILABLE"


def test_model_info_requires_auth_and_has_metrics(client):
    assert client.get("/model-info").status_code == 401
    d = client.get("/model-info", headers=auth()).json()
    assert d["trained"] and d["is_synthetic"] and "pr_auc" in d["metrics"] and d["version"]


# ---------- authentication ----------
@pytest.mark.parametrize("path", ["/transactions", "/alerts", "/transactions/stats", "/model-info"])
def test_missing_token_rejected(client, path):
    assert client.get(path).status_code == 401


def test_predict_missing_token(client):
    assert client.post("/predict", json=valid_payload()).status_code == 401


def test_invalid_signature_rejected(client):
    h = {"Authorization": f"Bearer {make_token(secret='x' * 40)}"}
    assert client.get("/transactions", headers=h).status_code == 401


def test_expired_token_rejected(client):
    h = {"Authorization": f"Bearer {make_token(exp_in=-10)}"}
    assert client.get("/transactions", headers=h).status_code == 401


def test_wrong_audience_rejected(client):
    h = {"Authorization": f"Bearer {make_token(aud='other')}"}
    assert client.get("/transactions", headers=h).status_code == 401


def test_alg_none_token_rejected(client):
    import base64, json, time
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    tok = (b({"alg": "none", "typ": "JWT"}) + "."
           + b({"sub": "evil", "aud": "authenticated", "exp": int(time.time()) + 60, "app_metadata": {"role": "admin"}}) + ".")
    assert client.get("/transactions", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_garbage_token_rejected(client):
    assert client.get("/transactions", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


# ---------- prediction ----------
def test_predict_success_and_persists(client):
    r = client.post("/predict", json=valid_payload(), headers=auth())
    assert r.status_code == 201
    t = r.json()["transaction"]
    assert 0.0 <= t["probability"] <= 1.0
    assert t["risk"] in {"Low", "Medium", "High"} and t["model_version"]
    assert t["user_id"] == "user-a"
    got = client.get(f"/transactions/{t['id']}", headers=auth()).json()
    assert got["probability"] == t["probability"]


def test_predict_risky_is_flagged_with_factors(client):
    r = client.post("/predict", json=valid_payload(**RISKY), headers=auth())
    t = r.json()["transaction"]
    assert t["is_flagged"] is True and t["review_status"] == "new" and len(t["contributing_factors"]) >= 3


def test_risk_matches_probability(client):
    for p in (valid_payload(), valid_payload(**RISKY)):
        t = client.post("/predict", json=p, headers=auth()).json()["transaction"]
        expected = "High" if t["probability"] >= 0.7 else "Medium" if t["probability"] >= 0.3 else "Low"
        assert t["risk"] == expected


def test_predict_503_without_model(client_no_model):
    r = client_no_model.post("/predict", json=valid_payload(), headers=auth())
    assert r.status_code == 503 and "unavailable" in r.json()["detail"].lower()
    assert client_no_model.get("/transactions", headers=auth()).json()["total"] == 0   # nothing fabricated/saved


@pytest.mark.parametrize("over", [
    {"amount": -5}, {"amount": 0}, {"amount": 2_000_000}, {"hour": 24}, {"hour": -1}, {"failed_attempts": 11},
    {"payment_method": "Bitcoin"}, {"branch": "Mars"}, {"transaction_reference": "a b"},
    {"transaction_reference": "x"}, {"amount": "abc"}, {"customer_avg_spend": -1}, {"new_device": "maybe"},
])
def test_invalid_input_rejected(client, over):
    assert client.post("/predict", json=valid_payload(**over), headers=auth()).status_code == 422


def test_missing_field_rejected(client):
    p = valid_payload()
    del p["hour"]
    assert client.post("/predict", json=p, headers=auth()).status_code == 422


def test_client_cannot_set_score_or_user(client):
    for extra in ({"probability": 0.0}, {"risk": "Low"}, {"user_id": "someone-else"}, {"is_flagged": False}):
        assert client.post("/predict", json=valid_payload(**extra), headers=auth()).status_code == 422


def test_nan_rejected(client):
    r = client.post("/predict", content='{"amount": NaN}', headers={**auth(), "Content-Type": "application/json"})
    assert r.status_code == 422


def test_rate_limit(settings):
    from fastapi.testclient import TestClient
    from app.factory import create_app
    settings.predict_rate_limit_per_min = 2
    with TestClient(create_app(settings)) as c:
        codes = [c.post("/predict", json=valid_payload(), headers=auth()).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


def test_body_size_limit(client):
    r = client.post("/predict", content=b"x" * 30000, headers={**auth(), "Content-Type": "application/json"})
    assert r.status_code == 413


# ---------- ownership ----------
def test_ownership_isolation(client):
    t = client.post("/predict", json=valid_payload(**RISKY), headers=auth("alice")).json()["transaction"]
    assert client.get(f"/transactions/{t['id']}", headers=auth("bob")).status_code == 404
    assert client.get("/transactions", headers=auth("bob")).json()["total"] == 0
    assert client.get("/alerts", headers=auth("bob")).json()["total"] == 0
    assert client.get("/transactions", headers=auth("alice")).json()["total"] == 1
    assert client.get("/transactions/stats", headers=auth("bob")).json()["total_transactions"] == 0


def test_reviewer_sees_all(client):
    client.post("/predict", json=valid_payload(), headers=auth("alice"))
    client.post("/predict", json=valid_payload(transaction_reference="TX-2"), headers=auth("bob"))
    assert client.get("/transactions", headers=auth("ann", "analyst")).json()["total"] == 2


def test_forged_role_in_user_metadata_ignored(client):
    import jwt, time
    from .conftest import SECRET
    tok = jwt.encode({"sub": "mallory", "aud": "authenticated", "exp": int(time.time()) + 600,
                      "user_metadata": {"role": "admin"}}, SECRET, algorithm="HS256")
    client.post("/predict", json=valid_payload(**RISKY), headers=auth("alice"))
    alert = client.get("/alerts", headers=auth("ann", "analyst")).json()["items"][0]
    r = client.patch(f"/alerts/{alert['id']}", json={"status": "confirmed_fraud"},
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_unknown_id_404_and_bad_id(client):
    assert client.get("/transactions/not-a-uuid", headers=auth()).status_code == 404
    assert client.get("/transactions/00000000-0000-0000-0000-000000000000", headers=auth()).status_code == 404


# ---------- list / filter / paginate ----------
def test_search_filter_pagination(client):
    for i in range(5):
        client.post("/predict", json=valid_payload(transaction_reference=f"ABC-{i}"), headers=auth())
    client.post("/predict", json=valid_payload(transaction_reference="ZED-1", **RISKY), headers=auth())
    d = client.get("/transactions?search=ABC&page_size=2&page=2", headers=auth()).json()
    assert d["total"] == 5 and len(d["items"]) == 2 and d["page"] == 2
    assert client.get("/transactions?search=%25", headers=auth()).json()["total"] == 0   # wildcard is escaped
    assert client.get("/transactions?risk=High", headers=auth()).json()["total"] in (0, 1)
    assert client.get("/transactions?risk=Bogus", headers=auth()).status_code == 422
    assert client.get("/transactions?page_size=1000", headers=auth()).status_code == 422
    assert client.get("/transactions?page=0", headers=auth()).status_code == 422


def test_stats(client):
    client.post("/predict", json=valid_payload(amount=100), headers=auth())
    client.post("/predict", json=valid_payload(transaction_reference="TX-9", amount=300, **{k: v for k, v in RISKY.items() if k != "amount"}), headers=auth())
    s = client.get("/transactions/stats", headers=auth()).json()
    assert s["total_transactions"] == 2 and s["total_amount"] == 400.0
    assert s["flagged"] + s["lower_risk"] == 2


# ---------- alerts ----------
def _make_alert(client, user="alice"):
    t = client.post("/predict", json=valid_payload(**RISKY), headers=auth(user)).json()["transaction"]
    assert t["is_flagged"]
    return t


def test_alert_review_persists(client):
    t = _make_alert(client)
    r = client.patch(f"/alerts/{t['id']}", json={"status": "confirmed_fraud", "notes": "Called customer"},
                     headers=auth("ann", "analyst"))
    assert r.status_code == 200 and r.json()["reviewed_by"] == "ann"
    again = client.get(f"/transactions/{t['id']}", headers=auth("alice")).json()
    assert again["review_status"] == "confirmed_fraud" and again["review_notes"] == "Called customer"
    assert client.get("/alerts?review_status=new", headers=auth("ann", "analyst")).json()["total"] == 0
    assert client.get("/alerts?review_status=confirmed_fraud", headers=auth("ann", "analyst")).json()["total"] == 1


def test_customer_cannot_review(client):
    t = _make_alert(client)
    r = client.patch(f"/alerts/{t['id']}", json={"status": "false_positive"}, headers=auth("alice"))
    assert r.status_code == 403
    assert client.patch(f"/alerts/{t['id']}", json={"status": "false_positive"}).status_code == 401


def test_invalid_review_status(client):
    t = _make_alert(client)
    r = client.patch(f"/alerts/{t['id']}", json={"status": "banana"}, headers=auth("ann", "analyst"))
    assert r.status_code == 422


def test_cannot_review_non_alert(client):
    t = client.post("/predict", json=valid_payload(), headers=auth()).json()["transaction"]
    if not t["is_flagged"]:
        r = client.patch(f"/alerts/{t['id']}", json={"status": "false_positive"}, headers=auth("ann", "analyst"))
        assert r.status_code == 404


def test_no_destructive_endpoint(client):
    assert client.delete("/transactions", headers=auth("root", "admin")).status_code == 405


# ---------- database errors ----------
def test_database_error_is_503(settings, model_path):
    from fastapi.testclient import TestClient
    from app.db.base import RepositoryError
    from app.factory import create_app

    class Broken:
        def create_transaction(self, *a, **k): raise RepositoryError("boom secret detail")
        def list_transactions(self, *a, **k): raise RepositoryError("boom")
        def stats(self, *a, **k): raise RepositoryError("boom")

    with TestClient(create_app(settings, repo=Broken())) as c:
        r = c.post("/predict", json=valid_payload(), headers=auth())
        assert r.status_code == 503 and "secret" not in r.text
        assert c.get("/transactions", headers=auth()).status_code == 503
        assert c.get("/transactions/stats", headers=auth()).status_code == 503


def test_cors_only_allowed_origin(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_asymmetric_es256_token_verified_via_jwks(settings, monkeypatch):
    """Supabase projects with asymmetric keys: token signed with an EC key, verified through (mocked) JWKS."""
    import time
    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from fastapi.testclient import TestClient
    from app import auth
    from app.factory import create_app

    private = ec.generate_private_key(ec.SECP256R1())

    class FakeJWKS:
        def __init__(self, url, **kw): pass
        def get_signing_key_from_jwt(self, token):
            class K: key = private.public_key()
            return K

    monkeypatch.setattr(auth.jwt, "PyJWKClient", FakeJWKS)
    auth._jwks_clients.clear()
    settings.supabase_url = "https://example.supabase.co"
    settings.supabase_jwt_secret = ""
    claims = {"sub": "es-user", "aud": "authenticated", "exp": int(time.time()) + 600, "app_metadata": {"role": "analyst"}}
    good = jwt.encode(claims, private, algorithm="ES256")
    other = jwt.encode(claims, ec.generate_private_key(ec.SECP256R1()), algorithm="ES256")
    with TestClient(create_app(settings)) as c:
        assert c.get("/transactions", headers={"Authorization": f"Bearer {good}"}).status_code == 200
        assert c.get("/transactions", headers={"Authorization": f"Bearer {other}"}).status_code == 401
    auth._jwks_clients.clear()


def test_hs256_token_rejected_when_only_jwks_configured(settings):
    from fastapi.testclient import TestClient
    from app.factory import create_app
    settings.supabase_url = "https://example.supabase.co"
    settings.supabase_jwt_secret = ""
    with TestClient(create_app(settings)) as c:
        assert c.get("/transactions", headers=auth()).status_code == 401   # HS256 token, no secret configured
