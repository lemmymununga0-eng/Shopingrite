"""Authentication (local demo + token rules) and server-side role enforcement."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import permissions as perm
from app.core.security import LOCAL_ISSUER, hash_password, verify_password
from app.factory import create_app

from .conftest import LOCAL_SECRET, SECRET, auth, cust, valid_payload

DEMO_PW = "DemoPass!2026"


def login(c, email="admin@example.com", pw=DEMO_PW):
    return c.post("/auth/local/login", json={"email": email, "password": pw})


def test_local_login_disabled_by_default(client):
    assert login(client).status_code == 404


def test_local_login_success_and_roles(local_client):
    for email, role in [("customer@example.com", "customer"), ("fraud.analyst@example.com", "fraud_analyst"),
                        ("security.analyst@example.com", "security_analyst"), ("admin@example.com", "admin")]:
        r = login(local_client, email)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user"]["role"] == role and "Not for production" in d["notice"] and "password" not in str(d["user"])
        me = local_client.get("/auth/me", headers={"Authorization": f"Bearer {d['access_token']}"}).json()
        assert me["role"] == role and me["is_staff"] == (role != "customer")


def test_local_login_failures_are_generic_and_recorded(local_client):
    wrong_pw = login(local_client, "admin@example.com", "nope")
    no_user = login(local_client, "ghost@example.com", "nope")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()                              # cannot tell "no such user" from "bad password"
    tok = login(local_client).json()["access_token"]
    ev = local_client.get("/security/events?category=authentication", headers={"Authorization": f"Bearer {tok}"}).json()
    assert ev["total"] >= 2 and ev["items"][0]["event_type"] == "auth.login_failed"


def test_local_login_rate_limited(local_settings):
    local_settings.login_rate_limit_per_min = 3
    with TestClient(create_app(local_settings)) as c:
        codes = [login(c, pw="bad").status_code for _ in range(5)]
    assert codes[:3] == [401] * 3 and 429 in codes[3:]


def test_inactive_user_cannot_sign_in(local_client):
    tok = login(local_client).json()
    from app.db.models import AppUser
    from sqlalchemy import select
    with local_client.app.state.db.session() as s:
        s.scalar(select(AppUser).where(AppUser.email == "customer@example.com")).is_active = False
    assert login(local_client, "customer@example.com").status_code == 401


def test_local_token_not_accepted_when_local_auth_disabled(settings):
    token = jwt.encode({"sub": "u", "aud": "authenticated", "iss": LOCAL_ISSUER, "exp": int(time.time()) + 600,
                        "app_metadata": {"role": "admin"}}, LOCAL_SECRET, algorithm="HS256")
    with TestClient(create_app(settings)) as c:                            # `settings` has local auth OFF
        assert c.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_local_issuer_token_with_wrong_secret_rejected(local_client):
    forged = jwt.encode({"sub": "u", "aud": "authenticated", "iss": LOCAL_ISSUER, "exp": int(time.time()) + 600,
                         "app_metadata": {"role": "admin"}}, "x" * 40, algorithm="HS256")
    assert local_client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_local_auth_refused_in_production(local_settings):
    local_settings.environment = "production"
    with pytest.raises(RuntimeError):
        with TestClient(create_app(local_settings)):
            pass


def test_short_local_secret_refused(local_settings):
    local_settings.local_auth_secret = "short"
    with pytest.raises(RuntimeError):
        with TestClient(create_app(local_settings)):
            pass


def test_password_hashing():
    h = hash_password("pw1")
    assert h != "pw1" and verify_password("pw1", h) and not verify_password("pw2", h) and not verify_password("pw1", "junk")


def test_role_comes_only_from_app_metadata(client):
    t = jwt.encode({"sub": "m", "aud": "authenticated", "exp": int(time.time()) + 600,
                    "user_metadata": {"role": "admin"}, "role": "admin"}, SECRET, algorithm="HS256")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {t}"}).json()
    assert me["role"] == "customer"
    t2 = jwt.encode({"sub": "m", "aud": "authenticated", "exp": int(time.time()) + 600,
                     "app_metadata": {"role": "superuser"}}, SECRET, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {t2}"}).json()["role"] == "customer"


def test_client_supplied_user_id_is_ignored(client):
    """The cart belongs to the token's subject, whatever the client sends."""
    r = client.post("/cart/items", json={"product_id": 1, "quantity": 1, "user_id": "someone-else"}, headers=cust("me"))
    assert r.status_code == 422


# --- the permission matrix, exercised against real endpoints ---
ENDPOINTS = [  # method, path, body, permission, allowed roles
    ("GET", "/inventory", None, "inventory.view"),
    ("GET", "/transactions", None, "fraud.view"),
    ("GET", "/model-info", None, "settings.view"),
    ("GET", "/security/events", None, "security.view"),
    ("GET", "/security/summary", None, "security.view"),
    ("GET", "/audit", None, "audit.view"),
    ("GET", "/admin/users", None, "users.manage"),
    ("GET", "/investigations", None, "cases.view"),
    ("GET", "/reports/overview", None, "reports.view"),
    ("GET", "/reports/fraud", None, "reports.fraud"),
    ("GET", "/reports/security", None, "reports.security"),
    ("GET", "/settings/integrations", None, "settings.view"),
    ("GET", "/scamwatch/providers", None, "scamwatch.view_all"),
]


@pytest.mark.parametrize("method,path,body,permission", ENDPOINTS)
def test_every_role_gets_exactly_the_permissions_in_the_matrix(client, method, path, body, permission):
    assert client.request(method, path).status_code == 401
    for role in perm.ROLES:
        r = client.request(method, path, json=body, headers=auth(f"u-{role}", role))
        expected_ok = perm.allowed(role, permission)
        assert (r.status_code == 200) == expected_ok, f"{role} {method} {path} -> {r.status_code}"
        if not expected_ok:
            assert r.status_code == 403


def test_legacy_analyst_role_means_fraud_analyst():
    assert perm.normalize_role("analyst") == "fraud_analyst"
    assert perm.normalize_role("hacker") == "customer" and perm.normalize_role(None) == "customer"


def test_docs_can_be_disabled(settings):
    settings.docs_enabled = False
    with TestClient(create_app(settings)) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
