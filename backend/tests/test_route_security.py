"""Every route must refuse anonymous callers unless it is on the explicit public list below. A new endpoint that forgets its
permission check fails this test instead of shipping."""
import re

from fastapi.routing import APIRoute

# (method, path) that anonymous visitors may call on purpose. Anything not here must answer 401/403 without credentials.
PUBLIC = {
    ("GET", "/health"), ("GET", "/store-info"), ("GET", "/categories"), ("GET", "/products"), ("GET", "/products/{product_id}"),
    ("GET", "/payments/methods"),            # which payment options exist (no personal data)
    ("POST", "/auth/local/login"), ("POST", "/auth/local/register"), 
}


def fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)


def test_every_route_rejects_anonymous_callers_unless_listed_public(client):
    leaks, seen_public = [], set()
    for route in client.app.routes:
        if not isinstance(route, APIRoute) or route.path in ("/docs", "/redoc", "/openapi.json"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in PUBLIC:
                seen_public.add((method, route.path))
                continue
            r = client.request(method, fill(route.path), json={} if method in ("POST", "PUT", "PATCH") else None)
            if r.status_code not in (401, 403):
                leaks.append((method, route.path, r.status_code))
    assert not leaks, f"endpoints reachable without credentials and not on the public list: {leaks}"
    assert PUBLIC == seen_public, f"stale entries in the public list (route no longer exists): {sorted(PUBLIC - seen_public)}"


def test_a_customer_token_is_refused_by_every_staff_route(client):
    from tests.conftest import cust
    h, leaks = cust("route-check"), []
    staff_prefixes = ("/staff", "/fraud", "/pca-demo", "/admin", "/alerts", "/investigations", "/security", "/reports", "/transactions", "/predict")
    for route in client.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(staff_prefixes):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            r = client.request(method, fill(route.path), headers=h, json={} if method in ("POST", "PUT", "PATCH") else None)
            if r.status_code != 403:
                leaks.append((method, route.path, r.status_code))
    assert not leaks, f"staff routes that did not answer 403 to a customer: {leaks}"


def test_api_responses_carry_security_headers(client):
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and h["cache-control"] == "no-store"
    assert "strict-transport-security" not in h              # only in production (HTTPS)


def test_hsts_is_sent_in_production(settings):
    from fastapi.testclient import TestClient
    from app.factory import create_app
    settings.environment, settings.local_auth_enabled = "production", False
    settings.supabase_url, settings.payments_simulated_enabled = "https://abc.supabase.co", False
    settings.seed_demo_data, settings.seed_legacy_demo, settings.store_is_demo, settings.docs_enabled = False, False, False, False
    settings.store_contact_email, settings.cors_origins = "shop@example.com", "https://shop.example.com"
    assert settings.production_problems() == []
    with TestClient(create_app(settings)) as c:
        assert "max-age=31536000" in c.get("/health").headers["strict-transport-security"]
