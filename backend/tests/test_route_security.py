"""Every route must refuse anonymous callers unless it is on the explicit public list below. A new endpoint that forgets its
permission check fails this test instead of shipping."""
import re

# (method, path) that anonymous visitors may call on purpose. Anything not here must answer 401/403 without credentials.
PUBLIC = {
    ("GET", "/health"), ("GET", "/store-info"), ("GET", "/categories"), ("GET", "/products"), ("GET", "/products/{product_id}"),
    ("GET", "/payments/methods"),            # which payment options exist (no personal data)
    ("POST", "/auth/local/login"), ("POST", "/auth/local/register"), 
}


def all_routes(app) -> set[tuple[str, str]]:
    """(METHOD, path) for every endpoint, read from the OpenAPI schema. `app.routes` is not stable across FastAPI releases
    (newer versions wrap included routers lazily), the schema is."""
    out = set()
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.add((method.upper(), path))
    assert len(out) > 40, f"suspiciously few routes found ({len(out)}): the route listing is broken"
    return out


def fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)


def test_every_route_rejects_anonymous_callers_unless_listed_public(client):
    leaks, seen_public = [], set()
    for method, path in sorted(all_routes(client.app)):
        if (method, path) in PUBLIC:
            seen_public.add((method, path))
            continue
        r = client.request(method, fill(path), json={} if method in ("POST", "PUT", "PATCH") else None)
        if r.status_code not in (401, 403):
            leaks.append((method, path, r.status_code))
    assert not leaks, f"endpoints reachable without credentials and not on the public list: {leaks}"
    assert PUBLIC == seen_public, f"stale entries in the public list (route no longer exists): {sorted(PUBLIC - seen_public)}"


def test_a_customer_token_is_refused_by_every_staff_route(client):
    from tests.conftest import cust
    h, leaks = cust("route-check"), []
    staff_prefixes = ("/staff", "/fraud", "/pca-demo", "/admin", "/alerts", "/investigations", "/security", "/reports", "/transactions", "/predict")
    checked = 0
    for method, path in sorted(all_routes(client.app)):
        if not path.startswith(staff_prefixes):
            continue
        checked += 1
        r = client.request(method, fill(path), headers=h, json={} if method in ("POST", "PUT", "PATCH") else None)
        if r.status_code != 403:
            leaks.append((method, path, r.status_code))
    assert checked > 20, f"only {checked} staff routes were checked"
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
