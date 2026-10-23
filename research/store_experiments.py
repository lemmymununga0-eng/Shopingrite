"""Store-system experiments for the paper: the real rule engine (store_risk_v1) driven through scripted checkouts, latency of the
checkout path, and engineering facts (endpoints, tables, tests, lines of code, CI state). From the repository root:

    python research/store_experiments.py scenarios
    python research/store_experiments.py latency
    python research/store_experiments.py facts
    python research/store_experiments.py all

Everything runs in-process against a throw-away SQLite database with the application's own code, simulated payments and a
test signing secret. Nothing here contacts a payment provider or any external service except the optional CI query in `facts`.
The scenario table is a behavioural description of the rules, NOT an estimate of fraud-detection accuracy (no labelled store data exists).
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
from _common import ROOT, RESULTS, environment, save  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.factory import create_app  # noqa: E402
from app.services import store_risk  # noqa: E402
from tests.conftest import SECRET, auth, order_body, put_in_cart  # noqa: E402

SKU = "DEMO-FP-001"                      # bananas, ZMW 24.99 per kg in the demonstration catalogue
ANALYST = auth("fraud-1", "fraud_analyst")


def customer(sub: str) -> dict:
    h = auth(sub, "customer")
    h["_sub"] = sub                                  # kept for the helper; removed before any request is sent
    return h
HIGH_VALUE_CENTS = 30_000               # ZMW 300: a deployment parameter chosen so grocery-sized baskets can reach it


def make_settings(tmp: Path, **over) -> Settings:
    return Settings(db_backend="sqlite", sqlite_path=tmp / "t.db", supabase_jwt_secret=SECRET, model_path=tmp / "none.joblib", ml_artifact_dir=tmp / "ml",
                    predict_rate_limit_per_min=100000, database_url=f"sqlite:///{(tmp / 'app.db').as_posix()}", seed_demo_data=True, seed_legacy_demo=True,
                    seed_zm_catalogue=False, checkout_rate_limit_per_min=100000, cart_rate_limit_per_min=100000, scamwatch_rate_limit_per_min=100000,
                    scamwatch_providers="heuristic", _env_file=None, **over)


def local_hour(h: int):
    """Make the engine's 'local hour' equal h whatever the clock says (the engine converts UTC to Zambian time)."""
    store_risk.LOCAL_UTC_OFFSET_HOURS = (h - datetime.now(timezone.utc).hour) % 24


def clean(h):
    return {k: v for k, v in h.items() if k != "_sub"}


def buy(c, h, qty=1, scenario="success", fulfilment="delivery", line="12 Test Street"):
    put_in_cart(c, clean(h), SKU, qty)
    body = order_body(fulfilment=fulfilment, payment={"method": "simulated", "scenario": scenario})
    if fulfilment == "collection":
        body.pop("address", None)
    else:
        body["address"] = {"line": line, "city": "Lusaka", "postal_code": "2000"}
    r = c.post("/orders", json=body, headers=clean(h))
    assert r.status_code == 201, r.text
    return r.json()


def assess(c, order):
    d = c.get(f"/staff/orders/{order['id']}", headers=ANALYST).json()
    a = d["assessments"][0]
    return {"score": a["score"], "decision": a["decision"], "rules": [{"rule": r["rule"], "points": r["points"], "text": r["text"]} for r in a["reasons"]],
            "case_opened": bool(d["case"]), "features": a["features"], "model_records": [{"model": m["model"], "status": m["status"]} for m in d["ml_predictions"]]}


def age(c, user_id: str, hours: float):
    """Move a customer's existing orders (and their payment attempts) back in time, so 'history' really is history."""
    from datetime import timedelta
    from sqlalchemy import select
    from app.db.models import Order, PaymentAttempt
    with c.app.state.db.session() as s:
        for o in s.scalars(select(Order).where(Order.user_id == user_id)):
            o.created_at = o.created_at - timedelta(hours=hours)
            for a in s.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == o.id)):
                a.created_at = a.created_at - timedelta(hours=hours)


def scenarios():
    out = {"environment": environment(), "settings": {"order_high_value_cents": HIGH_VALUE_CENTS, "order_bulk_quantity": 15, "order_velocity_per_hour": 4,
                                                       "order_rejection_burst": 5, "bands": {"high_at": store_risk.HIGH_AT, "review_at": store_risk.REVIEW_AT}},
           "scenarios": []}
    with tempfile.TemporaryDirectory() as d:
        with TestClient(create_app(make_settings(Path(d), order_high_value_cents=HIGH_VALUE_CENTS))) as c:
            def run(name, desc, fn, hour=12):
                local_hour(hour)
                order = fn()
                r = assess(c, order)
                out["scenarios"].append({"name": name, "description": desc, "order_total_cents": order["total_cents"], **r})
                print(f"{name}: {r['score']} {r['decision']} {[x['rule'] for x in r['rules']]} case={r['case_opened']}", flush=True)

            def history(h, n=2, line="12 Test Street", fulfilment="collection", hours_ago=72):
                local_hour(12)
                for _ in range(n):
                    buy(c, h, 1, fulfilment=fulfilment, line=line)
                if hours_ago:
                    age(c, h["_sub"], hours_ago)

            h = customer("c-routine"); history(h, 3)
            run("1 Routine repeat basket", "Returning customer, 3 earlier paid orders (3 days ago), 2 kg for collection", lambda: buy(c, h, 2, fulfilment="collection"))
            h = customer("c-first-medium")
            run("2 First-time medium basket", "New customer, 8 kg, collection", lambda: buy(c, h, 8, fulfilment="collection"))
            h = customer("c-first-bulk")
            run("3 First-time bulk basket", "New customer, 20 kg, home delivery", lambda: buy(c, h, 20))
            h = customer("c-spike"); history(h, 2)
            run("4 Spend spike", "Two earlier 1 kg orders, then 12 kg (about 12 times the usual total)", lambda: buy(c, h, 12, fulfilment="collection"))
            h = customer("c-burst"); history(h, 3, hours_ago=0)
            run("5 Order burst", "Three earlier orders within the last hour, then a fourth (limit 4 per hour)", lambda: buy(c, h, 1, fulfilment="collection"))
            h = customer("c-failures")
            local_hour(12)
            for _ in range(3):
                buy(c, h, 1, scenario="failure", fulfilment="collection")
            age(c, "c-failures", 3)
            run("6 Repeated failed payments", "Three failed payments earlier today, then a fourth order", lambda: buy(c, h, 1, fulfilment="collection"))
            h = customer("c-new-address"); history(h, 2, fulfilment="delivery")
            run("7 New delivery address", "Two deliveries to one address, then a delivery to another", lambda: buy(c, h, 1, line="99 New Road"))
            h = customer("c-night"); history(h, 2)
            run("8 Night-time order", "Ordinary 1 kg order placed at 02:00 local time", lambda: buy(c, h, 1, fulfilment="collection"), hour=2)
            h = customer("c-rejections")
            local_hour(12)
            admin = auth("admin-1", "admin")
            dairy = c.get("/products?search=DEMO-DE-003").json()["items"][0]["id"]
            for _ in range(5):                                           # five checkouts rejected for lack of stock within ten minutes
                put_in_cart(c, clean(h), "DEMO-DE-003", 1)
                c.patch(f"/inventory/{dairy}", json={"set_available": 0, "reason": "scripted rejection"}, headers=admin)
                assert c.post("/orders", json=order_body(), headers=clean(h)).status_code == 409
                c.patch(f"/inventory/{dairy}", json={"set_available": 5, "reason": "restock"}, headers=admin)
                for item in c.get("/cart", headers=clean(h)).json()["items"]:
                    c.delete(f"/cart/items/{item['item_id']}", headers=clean(h))
            run("9 Repeated rejected checkouts", "Five rejected checkouts in ten minutes, then an ordinary order", lambda: buy(c, h, 1, fulfilment="collection"))
            h = customer("c-combined"); history(h, 2, fulfilment="delivery")
            run("10 Combined warning signs", "Returning customer, 20 kg to a new address at 02:00", lambda: buy(c, h, 20, line="7 Unknown Street"), hour=2)
    out["rule_table"] = sorted({(r["rule"], r["points"], r["text"]) for s in out["scenarios"] for r in s["rules"]}, key=lambda t: (-t[1], t[0]))
    out["rule_table"] = [{"rule": a, "points": b, "text": t} for a, b, t in out["rule_table"]]
    save("store_scenarios", out)


def latency():
    n = 150
    out = {"environment": environment(), "n_orders": n, "note": "in-process FastAPI TestClient, SQLite, single thread, simulated payment, no network: indicative only"}
    with tempfile.TemporaryDirectory() as d:
        with TestClient(create_app(make_settings(Path(d)))) as c:
            local_hour(12)
            from tests.conftest import pid as product_id
            c.patch(f"/inventory/{product_id(c, SKU)}", json={"set_available": 1_000_000, "reason": "timing run"}, headers=auth("admin-1", "admin"))
            checkout, detail = [], []
            for i in range(n):
                h = auth(f"lat-{i}", "customer")
                put_in_cart(c, h, SKU, 2)
                body = order_body(fulfilment="collection", payment={"method": "simulated", "scenario": "success"})
                body.pop("address", None)
                t = time.perf_counter()
                r = c.post("/orders", json=body, headers=h)
                checkout.append((time.perf_counter() - t) * 1000)
                assert r.status_code == 201
                t = time.perf_counter()
                c.get(f"/staff/orders/{r.json()['id']}", headers=ANALYST)
                detail.append((time.perf_counter() - t) * 1000)
            # time the rule engine on its own
            from sqlalchemy import select
            from app.db.models import Order
            engine = []
            with c.app.state.db.session() as s:
                orders = s.scalars(select(Order).limit(n)).all()
                for o in orders:
                    t = time.perf_counter()
                    store_risk.compute(s, o, c.app.state.settings)
                    engine.append((time.perf_counter() - t) * 1000)

    def stats(a):
        a = np.array(a)
        return {"p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)), "p99_ms": float(np.percentile(a, 99)), "mean_ms": float(a.mean())}
    out["checkout_post_orders"] = stats(checkout)
    out["staff_order_detail_get"] = stats(detail)
    out["rule_engine_compute_only"] = stats(engine)
    save("store_latency", out)
    print(json.dumps({k: out[k] for k in ("checkout_post_orders", "rule_engine_compute_only")}, indent=1))


def lines(root: Path, pats) -> int:
    total = 0
    for p in pats:
        for f in root.rglob(p):
            if any(x in f.parts for x in ("node_modules", "dist", "__pycache__", "test-results", "_scratch")):
                continue
            total += sum(1 for _ in f.open(encoding="utf8", errors="ignore"))
    return total


def facts():
    from app.db.models import Base
    with tempfile.TemporaryDirectory() as d:
        app = create_app(make_settings(Path(d)))
        spec = app.openapi()
    ops = [(m.upper(), p) for p, v in spec["paths"].items() for m in v if m.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}]
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=ROOT / "backend", capture_output=True, text=True, timeout=600)
    last = [ln for ln in collected.stdout.splitlines() if "test" in ln and "collected" in ln or ln.strip().endswith("tests collected")]
    n_tests = next((int(ln.split()[0]) for ln in reversed(collected.stdout.splitlines()) if ln.split() and ln.split()[0].isdigit() and "test" in ln), None)
    ci = None
    try:
        r = json.load(urllib.request.urlopen("https://api.github.com/repos/lemmymununga0-eng/Shopingrite/actions/runs?per_page=1", timeout=30))["workflow_runs"][0]
        jobs = json.load(urllib.request.urlopen(r["jobs_url"], timeout=30))["jobs"]
        ci = {"run_number": r["run_number"], "commit": r["head_sha"][:7], "conclusion": r["conclusion"], "jobs": {j["name"]: j["conclusion"] for j in jobs}}
    except Exception as exc:                                      # offline: leave it out rather than guess
        ci = {"error": type(exc).__name__}
    out = {"environment": environment(), "api_operations": len(ops), "api_paths": len(spec["paths"]), "database_tables": len(Base.metadata.tables),
           "table_names": sorted(Base.metadata.tables), "backend_tests_collected": n_tests,
           "lines_of_code": {"backend_app_py": lines(ROOT / "backend" / "app", ["*.py"]), "backend_tests_py": lines(ROOT / "backend" / "tests", ["*.py"]),
                             "frontend_src_js_jsx": lines(ROOT / "frontend" / "src", ["*.js", "*.jsx"]), "research_py": lines(ROOT / "research", ["*.py"])},
           "ci_latest": ci}
    save("store_facts", out)
    print(json.dumps({k: out[k] for k in ("api_operations", "database_tables", "backend_tests_collected", "lines_of_code", "ci_latest")}, indent=1))


STEPS = {"scenarios": scenarios, "latency": latency, "facts": facts}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=[*STEPS, "all"])
    a = ap.parse_args()
    for name in (STEPS if a.step == "all" else [a.step]):
        STEPS[name]()
