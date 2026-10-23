"""The post-deploy smoke test script (scripts/verify_deployment.py): it must pass a correctly configured production app and
fail loudly on each misconfiguration it is meant to catch."""
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_deployment as vd  # noqa: E402

from app.factory import create_app  # noqa: E402


def failures(rep):
    return [name for level, name, _ in rep.rows if level == "FAIL"]


def production(settings):
    settings.environment, settings.local_auth_enabled = "production", False
    settings.supabase_url, settings.supabase_anon_key = "https://abc.supabase.co", "anon-key-value"
    settings.payments_simulated_enabled = False
    settings.seed_demo_data = settings.seed_legacy_demo = settings.store_is_demo = settings.docs_enabled = False
    settings.store_contact_email, settings.cors_origins = "shop@example.com", "https://shop.example.com"
    settings.flw_secret_key, settings.flw_webhook_hash = "FLWSECK_TEST-abc", "hash"
    assert settings.production_problems() == []
    return settings


def test_a_correct_production_app_passes_every_required_check(settings):
    with TestClient(create_app(production(settings)), base_url="https://api.test") as c:
        rep = vd.run("https://api.test", None, client=c)
    assert failures(rep) == [], rep.rows


def test_a_dev_app_fails_the_production_checks_but_passes_in_dev_mode(local_settings):
    with TestClient(create_app(local_settings), base_url="https://api.test") as c:
        bad = failures(vd.run("https://api.test", None, client=c))
        good = failures(vd.run("https://api.test", None, allow_dev=True, client=c))
    assert "API runs in production mode" in bad and "local demo sign-in is OFF" in bad and "store is not labelled a demonstration" in bad
    assert "simulated payments are OFF" in bad
    assert good == [], good


def canned(site_ok=True, cors="https://shop.example.com", csp=True):
    api_headers = {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "strict-transport-security": "max-age=1"}

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u.startswith("https://api.test"):
            path = req.url.path
            if req.method == "OPTIONS":
                origin = req.headers.get("origin")
                allow = cors if cors != "echo" else origin
                return httpx.Response(200, headers={"access-control-allow-origin": allow} if allow else {})
            if path == "/health":
                return httpx.Response(200, headers=api_headers, json={"status": "ok", "app_database": "ok", "environment": "production",
                                                                      "local_auth_enabled": False, "auth_configured": True})
            if path == "/store-info":
                return httpx.Response(200, json={"is_demo": False, "contact_email": "shop@example.com", "currency": "ZMW"})
            if path == "/products":
                return httpx.Response(200, json={"total": 3, "items": []})
            if path == "/payments/methods":
                return httpx.Response(200, json={"methods": [{"id": "card", "available": True}, {"id": "simulated", "available": False}]})
            if path == "/docs":
                return httpx.Response(404)
            return httpx.Response(401)
        headers = {"x-frame-options": "DENY"}
        if csp:
            headers["content-security-policy"] = "default-src 'self'"
        if req.url.path in ("/", "/shop/orders") and site_ok:
            return httpx.Response(200, headers=headers, text='<html><div id="root"></div></html>')
        return httpx.Response(404, headers=headers, text="not found")
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_healthy_deployment_passes_including_the_website_and_cors():
    rep = vd.run("https://api.test", "https://shop.example.com", client=canned())
    assert failures(rep) == [], rep.rows


@pytest.mark.parametrize("kwargs,expected", [
    ({"cors": "*"}, "CORS refuses other websites"),
    ({"cors": "echo"}, "CORS refuses other websites"),                       # reflects any origin: unsafe
    ({"cors": None}, "CORS allows your website"),
    ({"site_ok": False}, "deep links open the app (SPA rewrite)"),
    ({"csp": False}, "website sends a Content-Security-Policy"),
])
def test_each_misconfiguration_is_reported(kwargs, expected):
    assert expected in failures(vd.run("https://api.test", "https://shop.example.com", client=canned(**kwargs)))


def test_an_unreachable_api_fails_with_a_clear_exit_code(capsys):
    def boom(req):
        raise httpx.ConnectError("no route")
    c = httpx.Client(transport=httpx.MockTransport(boom))
    rep = vd.run("https://down.test", None, client=c)
    assert failures(rep)
