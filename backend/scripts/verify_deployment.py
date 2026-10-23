"""Smoke-test a deployed store from the outside. Run it after every deploy.

    python scripts/verify_deployment.py --api https://my-api.onrender.com --site https://my-shop.vercel.app
    python scripts/verify_deployment.py --api http://127.0.0.1:8000 --allow-dev      # against a local server (skips production-only checks)

It sends only anonymous requests (no passwords, no keys, nothing is created or changed) and checks that:
  * the API is up, the database answers, and the API runs as `production` with local demo sign-in OFF;
  * the store is not labelled a demonstration and has a real contact e-mail;
  * interactive API docs are off, staff and fraud endpoints refuse anonymous callers, and security headers are present;
  * CORS allows your website's address and refuses a stranger's;
  * the website serves, rewrites deep links to the app, and sends its security headers;
  * real payment methods are switched on (a warning, not a failure, while you are still on test keys).

Exit code 0 = every required check passed, 1 = at least one failed. Warnings never fail the run.
"""
import argparse
import sys

import httpx

STRANGER = "https://evil.example.org"


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level: str, name: str, detail: str = ""):
        self.rows.append((level, name, detail))
        print(f"  [{level:4}] {name}" + (f" - {detail}" if detail else ""))

    def ok(self, name, detail=""):
        self.add("PASS", name, detail)

    def fail(self, name, detail=""):
        self.add("FAIL", name, detail)

    def warn(self, name, detail=""):
        self.add("WARN", name, detail)

    def check(self, cond: bool, name: str, detail_if_fail: str = ""):
        (self.ok if cond else self.fail)(name, "" if cond else detail_if_fail)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if r[0] == "FAIL")


def run(api: str, site: str | None, allow_dev: bool = False, client: httpx.Client | None = None) -> Report:
    api, rep = api.rstrip("/"), Report()
    c = client or httpx.Client(timeout=20.0, follow_redirects=False)

    def get(url, **kw):
        try:
            return c.get(url, **kw)
        except httpx.HTTPError as exc:
            rep.fail(f"GET {url}", f"{type(exc).__name__}")
            return None

    print(f"API  {api}")
    h = get(f"{api}/health")
    if h is None or h.status_code != 200:
        rep.fail("API /health answers 200", f"status {getattr(h, 'status_code', 'no answer')}")
        return rep
    body = h.json()
    rep.check(body.get("status") == "ok", "API reports status ok")
    rep.check(body.get("app_database") == "ok", "database answers", f"app_database={body.get('app_database')}")
    if allow_dev:
        rep.warn("production-only checks skipped (--allow-dev)")
    else:
        rep.check(body.get("environment") == "production", "API runs in production mode", f"environment={body.get('environment')}")
        rep.check(body.get("local_auth_enabled") is False, "local demo sign-in is OFF", "LOCAL_AUTH_ENABLED must be false")
        rep.check(api.startswith("https://"), "API is served over HTTPS", api)
    rep.check(body.get("auth_configured") is True, "real sign-in (Supabase) is configured", "SUPABASE_URL / keys missing")

    info = get(f"{api}/store-info")
    if info is not None and info.status_code == 200:
        s = info.json()
        if not allow_dev:
            rep.check(s.get("is_demo") is False, "store is not labelled a demonstration", "STORE_IS_DEMO must be false")
            rep.check("@" in (s.get("contact_email") or ""), "store has a contact e-mail", "STORE_CONTACT_EMAIL is empty")
        rep.check(s.get("currency") == "ZMW", "store currency is ZMW", f"currency={s.get('currency')}")
    else:
        rep.fail("GET /store-info answers 200")

    prods = get(f"{api}/products?page_size=1")
    rep.check(prods is not None and prods.status_code == 200, "product catalogue answers")
    if prods is not None and prods.status_code == 200 and prods.json().get("total", 0) == 0:
        rep.warn("the catalogue is empty", "add products in the staff console before opening the shop")

    pm = get(f"{api}/payments/methods")
    if pm is not None and pm.status_code == 200:
        methods = {m["id"]: m for m in pm.json().get("methods", [])}
        online = [k for k in ("card", "mtn_momo", "airtel_money") if methods.get(k, {}).get("available")]
        if allow_dev:
            pass
        elif online:
            rep.ok("online payment methods available", ", ".join(online))
        else:
            rep.warn("no online payment method is available", "FLW_SECRET_KEY is not set or invalid; customers can only use cash on delivery, if enabled")
        if not allow_dev:
            rep.check(not methods.get("simulated", {}).get("available"), "simulated payments are OFF",
                      "PAYMENTS_SIMULATED_ENABLED must be false: anyone could 'pay' for free")

    docs = get(f"{api}/docs")
    if not allow_dev:
        rep.check(docs is not None and docs.status_code in (404, 401, 403), "interactive API docs are off", f"/docs answered {getattr(docs, 'status_code', '?')}")
    for path in ("/staff/orders", "/fraud/model-status", "/staff/ml-summary", "/admin/users", "/alerts", "/transactions"):
        r = get(f"{api}{path}")
        if r is not None and r.status_code == 404 and path == "/admin/users":
            continue                                                 # route may not exist; that is fine
        rep.check(r is not None and r.status_code in (401, 403), f"{path} refuses anonymous callers", f"answered {getattr(r, 'status_code', '?')}")

    hh = h.headers
    rep.check(hh.get("x-content-type-options") == "nosniff", "API sends X-Content-Type-Options")
    rep.check(hh.get("x-frame-options") == "DENY", "API sends X-Frame-Options")
    if not allow_dev:
        rep.check("max-age" in hh.get("strict-transport-security", ""), "API sends HSTS", "missing Strict-Transport-Security")

    if site:
        site = site.rstrip("/")
        pre = c.options(f"{api}/products", headers={"Origin": site, "Access-Control-Request-Method": "GET"})
        rep.check(pre.headers.get("access-control-allow-origin") == site, "CORS allows your website", "set CORS_ORIGINS to exactly the site address")
        bad = c.options(f"{api}/products", headers={"Origin": STRANGER, "Access-Control-Request-Method": "GET"})
        rep.check(bad.headers.get("access-control-allow-origin") not in (STRANGER, "*"), "CORS refuses other websites",
                  f"allowed {bad.headers.get('access-control-allow-origin')}")
        print(f"SITE {site}")
        home = get(site)
        rep.check(home is not None and home.status_code == 200 and "<div id=\"root\">" in home.text, "website serves the app")
        deep = get(f"{site}/shop/orders")
        rep.check(deep is not None and deep.status_code == 200 and "<div id=\"root\">" in deep.text, "deep links open the app (SPA rewrite)")
        if home is not None:
            sh = home.headers
            rep.check("default-src" in sh.get("content-security-policy", ""), "website sends a Content-Security-Policy")
            rep.check(sh.get("x-frame-options") == "DENY", "website sends X-Frame-Options")
            if not allow_dev:
                rep.check(site.startswith("https://"), "website is served over HTTPS", site)
    else:
        rep.warn("--site not given: website and CORS checks skipped")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", required=True, help="API address, e.g. https://my-api.onrender.com")
    ap.add_argument("--site", help="website address, e.g. https://my-shop.vercel.app")
    ap.add_argument("--allow-dev", action="store_true", help="local/dev server: skip production-only checks")
    args = ap.parse_args(argv)
    rep = run(args.api, args.site, args.allow_dev)
    print(f"\n{len(rep.rows) - rep.failed} ok/warn, {rep.failed} failed")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
