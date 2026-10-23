"""Real-payment flow against a FAKE Flutterwave (httpx MockTransport). Nothing here contacts the real service, so these
tests prove our logic (verification, mismatches, late payments, webhooks, refunds), not Flutterwave's behaviour.
The live sandbox check is a separate manual step (docs/DEPLOYMENT.md)."""
import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import AuditEvent, Order, PaymentAttempt, PaymentEvent, SecurityEvent, utcnow
from app.factory import create_app
from app.services import payment_flow
from app.services.flutterwave import FlutterwaveClient, FlutterwaveError

from .conftest import admin_h, cust, order_body, put_in_cart, stock

KEY, HOOK = "FLWSECK_TEST-abc123", "whsec-test-hash"
SKU = "DEMO-FP-001"


class FakeFlutterwave:
    """Just enough of the v3 API: create link, verify_by_reference, refund. `txns` maps tx_ref -> what the customer did."""

    def __init__(self):
        self.txns, self.created, self.refunds, self.calls, self.down = {}, [], [], [], False

    def pay(self, tx_ref, amount, currency="ZMW", status="successful", txn_id=777001):
        self.txns[tx_ref] = {"id": txn_id, "tx_ref": tx_ref, "amount": amount, "currency": currency, "status": status,
                             "payment_type": "mobilemoneyzm", "processor_response": "Approved"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if self.down:
            raise httpx.ConnectError("network down")
        path = request.url.path
        if request.method == "POST" and path.endswith("/payments"):
            body = json.loads(request.content)
            self.created.append(body)
            return httpx.Response(200, json={"status": "success", "message": "Hosted Link",
                                             "data": {"link": f"https://checkout.flutterwave.com/v3/hosted/pay/{body['tx_ref']}"}})
        if path.endswith("/transactions/verify_by_reference"):
            t = self.txns.get(request.url.params["tx_ref"])
            if t is None:
                return httpx.Response(400, json={"status": "error", "message": "No transaction was found for this id", "data": None})
            return httpx.Response(200, json={"status": "success", "message": "Transaction fetched successfully", "data": t})
        if path.endswith("/refund"):
            self.refunds.append(path)
            return httpx.Response(200, json={"status": "success", "message": "Transaction refund initiated",
                                             "data": {"id": 1, "status": "completed", "amount_refunded": 10}})
        return httpx.Response(404, json={"status": "error", "message": "unknown", "data": None})


@pytest.fixture()
def fake():
    return FakeFlutterwave()


@pytest.fixture()
def flw_settings(settings):
    settings.flw_secret_key, settings.flw_webhook_hash = KEY, HOOK
    settings.frontend_url = "https://shop.example.com"
    return settings


@pytest.fixture()
def fclient(flw_settings, fake):
    client = FlutterwaveClient(KEY, transport=httpx.MockTransport(fake.handler))
    with TestClient(create_app(flw_settings, flw=client)) as c:
        yield c


def place(client, h, method="card", qty=2):
    put_in_cart(client, h, SKU, qty)
    r = client.post("/orders", json=order_body(payment={"method": method}), headers=h)
    assert r.status_code == 201, r.text
    o = r.json()
    return o, o["payment_attempts"][-1]["reference"]


def order_row(client, order_id):
    with client.app.state.db.session() as s:
        o = s.get(Order, order_id)
        return o.status, o.payment_status


def hook(client, ref, txn_id=777001, status="successful", secret=HOOK):
    body = {"event": "charge.completed", "data": {"id": txn_id, "tx_ref": ref, "status": status}}
    return client.post("/payments/webhooks/flutterwave", content=json.dumps(body),
                       headers={"verif-hash": secret, "content-type": "application/json"})


# --------------------------------------------------------------------------------------------- availability
def test_online_methods_are_offered_in_test_mode_when_configured(fclient):
    ms = {m["id"]: m for m in fclient.get("/payments/methods").json()["methods"]}
    for k in ("card", "airtel_money", "mtn_momo"):
        assert ms[k]["available"] is True and ms[k]["mode"] == "TEST"


def test_online_methods_are_refused_before_stock_is_touched_when_not_configured(client):
    off = {m["id"]: m for m in client.get("/payments/methods").json()["methods"]}     # no key configured
    assert all(off[k]["available"] is False for k in ("card", "airtel_money", "mtn_momo"))
    put_in_cart(client, cust(), SKU, 1)
    assert client.post("/orders", json=order_body(payment={"method": "card"}), headers=cust()).status_code == 503
    assert stock(client, SKU) == 120


def test_creating_an_order_makes_no_network_call_and_waits_for_payment(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    assert fake.calls == []
    a = o["payment_attempts"][0]
    assert o["status"] == "awaiting_payment" and o["payment_status"] == "pending"
    assert a["provider"] == "flutterwave" and a["mode"] == "TEST" and a["status"] == "pending"
    assert "test mode" in o["payment_notice"].lower()
    assert stock(fclient, SKU) == 118                                                  # held while the customer pays


# --------------------------------------------------------------------------------------------- hosted link
def test_checkout_link_is_created_once_with_the_right_payload_and_never_card_data(fclient, fake):
    h = cust()
    o, ref = place(fclient, h, method="mtn_momo")
    r = fclient.post(f"/payments/{ref}/checkout-link", headers=h)
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.flutterwave.com/")
    assert fclient.post(f"/payments/{ref}/checkout-link", headers=h).json() == r.json()
    assert len(fake.created) == 1
    sent = fake.created[0]
    assert sent["tx_ref"] == ref and sent["currency"] == "ZMW" and sent["payment_options"] == "mobilemoneyzambia"
    assert sent["amount"] == o["total_cents"] / 100
    assert sent["redirect_url"] == f"https://shop.example.com/shop/payment/{o['id']}"
    assert sent["customer"]["email"] == "shopper@example.com" and sent["customer"]["phonenumber"] == "+260971234567"
    assert not any(k in json.dumps(sent).lower() for k in ("cvv", "card_number", "pin"))


def test_checkout_link_rules(fclient, fake):
    owner, other = cust("cust-1"), cust("cust-2")
    o, ref = place(fclient, owner)
    assert fclient.post(f"/payments/{ref}/checkout-link", headers=other).status_code == 404
    assert fclient.post("/payments/PAY-ZZZZZZZZ/checkout-link", headers=owner).status_code == 404
    assert fclient.post(f"/payments/{ref}/checkout-link").status_code == 401
    fclient.post(f"/orders/{o['id']}/cancel", headers=owner)
    assert fclient.post(f"/payments/{ref}/checkout-link", headers=owner).status_code == 409   # cancelled: cannot be paid


def test_checkout_link_when_flutterwave_is_down_is_a_clean_502(fclient, fake):
    h = cust()
    _, ref = place(fclient, h)
    fake.down = True
    r = fclient.post(f"/payments/{ref}/checkout-link", headers=h)
    assert r.status_code == 502 and KEY not in r.text


# --------------------------------------------------------------------------------------------- verification
def test_verify_before_paying_stays_pending_and_after_paying_confirms(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    r = fclient.post(f"/payments/{ref}/verify", headers=h)
    assert r.status_code == 200 and r.json()["outcome"] == "pending" and r.json()["order"]["payment_status"] == "pending"
    fake.pay(ref, o["total_cents"] / 100)
    r = fclient.post(f"/payments/{ref}/verify", headers=h)
    d = r.json()
    assert d["outcome"] == "succeeded" and d["order"]["status"] == "confirmed" and d["order"]["payment_status"] == "paid"
    with fclient.app.state.db.session() as s:
        assert s.scalar(select(PaymentAttempt.provider_reference).where(PaymentAttempt.reference == ref)) == "777001"
    assert fclient.post(f"/payments/{ref}/verify", headers=h).json()["outcome"] == "unchanged"   # repeat is harmless
    assert order_row(fclient, o["id"]) == ("confirmed", "paid")


def test_the_redirect_url_cannot_fake_a_payment(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    r = fclient.post(f"/payments/{ref}/verify?status=successful&transaction_id=1", headers=h)
    assert r.json()["outcome"] == "pending" and order_row(fclient, o["id"]) == ("awaiting_payment", "pending")


def test_wrong_amount_or_currency_is_never_accepted_and_is_flagged(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.pay(ref, 1.00)                                               # paid far too little
    d = fclient.post(f"/payments/{ref}/verify", headers=h).json()
    assert d["outcome"] == "mismatch" and d["order"]["payment_status"] != "paid" and d["order"]["status"] != "confirmed"
    with fclient.app.state.db.session() as s:
        assert s.scalar(select(SecurityEvent).where(SecurityEvent.event_type == "payment.amount_mismatch")) is not None
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "payment.amount_mismatch")) is not None
    o2, ref2 = place(fclient, cust("cust-2"))
    fake.pay(ref2, o2["total_cents"] / 100, currency="USD")
    assert fclient.post(f"/payments/{ref2}/verify", headers=cust("cust-2")).json()["outcome"] == "mismatch"


def test_overpayment_is_accepted(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.pay(ref, o["total_cents"] / 100 + 5)
    assert fclient.post(f"/payments/{ref}/verify", headers=h).json()["outcome"] == "succeeded"


def test_declined_payment_fails_the_attempt_and_allows_a_retry(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.pay(ref, o["total_cents"] / 100, status="failed")
    d = fclient.post(f"/payments/{ref}/verify", headers=h).json()
    assert d["outcome"] == "failed" and d["order"]["status"] == "payment_failed" and stock(fclient, SKU) == 118
    r = fclient.post(f"/orders/{o['id']}/pay", json={"method": "card"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "awaiting_payment"
    assert [a["status"] for a in r.json()["payment_attempts"]] == ["failed", "pending"]


def test_verify_when_flutterwave_is_unreachable_is_a_502_and_changes_nothing(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.down = True
    assert fclient.post(f"/payments/{ref}/verify", headers=h).status_code == 502
    assert order_row(fclient, o["id"]) == ("awaiting_payment", "pending")


def test_only_the_owner_can_verify_or_cancel(fclient, fake):
    _, ref = place(fclient, cust("cust-1"))
    for path in ("verify", "cancel"):
        assert fclient.post(f"/payments/{ref}/{path}", headers=cust("cust-2")).status_code == 404
        assert fclient.post(f"/payments/{ref}/{path}", headers=admin_h()).status_code == 404


def test_simulated_scenarios_cannot_be_used_on_a_real_attempt(fclient):
    h = cust()
    _, ref = place(fclient, h)
    assert fclient.post(f"/payments/{ref}/simulate", json={"outcome": "succeeded"}, headers=h).status_code == 404


# --------------------------------------------------------------------------------------------- cancel + late payments
def test_cancelling_the_attempt_allows_a_retry_but_not_when_they_really_paid(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    d = fclient.post(f"/payments/{ref}/cancel", headers=h).json()
    assert d["outcome"] == "cancelled" and d["order"]["status"] == "payment_failed"
    o2, ref2 = place(fclient, cust("cust-2"))
    fake.pay(ref2, o2["total_cents"] / 100)                           # they paid, then pressed "cancel"
    d2 = fclient.post(f"/payments/{ref2}/cancel", headers=cust("cust-2")).json()
    assert d2["outcome"] == "succeeded" and d2["order"]["payment_status"] == "paid"


def test_payment_arriving_after_the_attempt_was_cancelled_is_still_honoured(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fclient.post(f"/payments/{ref}/cancel", headers=h)
    fake.pay(ref, o["total_cents"] / 100)                             # customer paid on the open payment page
    assert hook(fclient, ref).json()["outcome"] == "succeeded"
    assert order_row(fclient, o["id"]) == ("confirmed", "paid")


def test_payment_after_the_order_was_cancelled_is_flagged_for_refund_then_refunded(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fclient.post(f"/orders/{o['id']}/cancel", headers=h)
    fake.pay(ref, o["total_cents"] / 100)
    assert hook(fclient, ref).json()["outcome"] == "succeeded"
    assert order_row(fclient, o["id"]) == ("cancelled", "refund_pending")
    assert fclient.post(f"/orders/{o['id']}/refund", headers=h).status_code == 403          # customers cannot refund
    r = fclient.post(f"/orders/{o['id']}/refund", headers=admin_h())
    assert r.status_code == 200 and r.json()["payment_status"] == "refunded"
    assert fake.refunds == ["/v3/transactions/777001/refund"]
    assert fclient.post(f"/orders/{o['id']}/refund", headers=admin_h()).status_code == 409    # only once
    assert len(fake.refunds) == 1


def test_cancelling_a_paid_online_order_needs_a_refund(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.pay(ref, o["total_cents"] / 100)
    fclient.post(f"/payments/{ref}/verify", headers=h)
    c = fclient.post(f"/orders/{o['id']}/cancel", headers=h).json()
    assert c["status"] == "cancelled" and c["payment_status"] == "refund_pending" and stock(fclient, SKU) == 120
    assert fclient.post(f"/orders/{o['id']}/refund", headers=admin_h()).json()["payment_status"] == "refunded"


def test_refund_refused_when_nothing_is_waiting_for_one(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    assert fclient.post(f"/orders/{o['id']}/refund", headers=admin_h()).status_code == 409
    assert fclient.post("/orders/not-a-uuid/refund", headers=admin_h()).status_code == 404


# --------------------------------------------------------------------------------------------- webhook
def test_webhook_needs_the_secret_hash(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.pay(ref, o["total_cents"] / 100)
    assert hook(fclient, ref, secret="wrong").status_code == 401
    assert fclient.post("/payments/webhooks/flutterwave", json={"data": {"tx_ref": ref, "id": 1}}).status_code == 401
    assert order_row(fclient, o["id"]) == ("awaiting_payment", "pending")
    with fclient.app.state.db.session() as s:
        assert s.scalar(select(SecurityEvent).where(SecurityEvent.event_type == "payment.webhook_bad_signature")) is not None


def test_webhook_confirms_via_verification_and_duplicates_are_ignored(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.pay(ref, o["total_cents"] / 100)
    first = hook(fclient, ref)
    assert first.status_code == 200 and first.json()["outcome"] == "succeeded"
    assert order_row(fclient, o["id"]) == ("confirmed", "paid")
    assert hook(fclient, ref).json()["outcome"] == "duplicate"
    with fclient.app.state.db.session() as s:
        evs = s.scalars(select(PaymentEvent).where(PaymentEvent.provider == "flutterwave")).all()
        assert len(evs) == 1 and evs[0].applied is True


def test_webhook_claiming_success_that_flutterwave_does_not_confirm_changes_nothing(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)                                        # Flutterwave knows nothing about this reference
    assert hook(fclient, ref, status="successful").json()["outcome"] == "pending"
    assert order_row(fclient, o["id"]) == ("awaiting_payment", "pending")


def test_webhook_for_other_references_is_acknowledged_and_ignored(fclient, fake):
    assert hook(fclient, "SOME-OTHER-APP-REF").json() == {"status": "ignored"}
    assert hook(fclient, "PAY-AAAAAAAA").json()["outcome"] == "unknown"
    assert fclient.post("/payments/webhooks/flutterwave", content="not json", headers={"verif-hash": HOOK}).json() == {"status": "ignored"}


def test_webhook_is_refused_when_no_hash_is_configured(flw_settings, fake):
    flw_settings.flw_webhook_hash = ""
    with TestClient(create_app(flw_settings, flw=FlutterwaveClient(KEY, transport=httpx.MockTransport(fake.handler)))) as c:
        assert c.post("/payments/webhooks/flutterwave", json={}, headers={"verif-hash": ""}).status_code == 401
        assert c.post("/payments/webhooks/flutterwave", json={}).status_code == 401


def test_webhook_when_flutterwave_cannot_be_reached_returns_502_so_it_retries(fclient, fake):
    h = cust()
    _, ref = place(fclient, h)
    fake.down = True
    assert hook(fclient, ref).status_code == 502


# --------------------------------------------------------------------------------------------- reconciliation
def test_reconciler_settles_payments_whose_webhook_never_came(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    fake.pay(ref, o["total_cents"] / 100)
    app = fclient.app
    assert payment_flow.reconcile_pending(app.state.db, app.state.flw, app.state.events) == 0   # too fresh: left alone
    with app.state.db.session() as s:
        s.scalar(select(PaymentAttempt).where(PaymentAttempt.reference == ref)).created_at = utcnow() - timedelta(minutes=5)
    assert payment_flow.reconcile_pending(app.state.db, app.state.flw, app.state.events) == 1
    assert order_row(fclient, o["id"]) == ("confirmed", "paid")
    assert payment_flow.reconcile_pending(app.state.db, app.state.flw, app.state.events) == 0


def test_reconciler_survives_flutterwave_being_down(fclient, fake):
    h = cust()
    _, ref = place(fclient, h)
    with fclient.app.state.db.session() as s:
        s.scalar(select(PaymentAttempt).where(PaymentAttempt.reference == ref)).created_at = utcnow() - timedelta(minutes=5)
    fake.down = True
    app = fclient.app
    assert payment_flow.reconcile_pending(app.state.db, app.state.flw, app.state.events) == 0


def test_reconcile_runs_before_expiry_so_a_last_minute_payment_is_not_lost(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    with fclient.app.state.db.session() as s:
        s.get(Order, o["id"]).payment_due_at = utcnow() - timedelta(minutes=1)
        s.scalar(select(PaymentAttempt).where(PaymentAttempt.reference == ref)).created_at = utcnow() - timedelta(minutes=5)
    fake.pay(ref, o["total_cents"] / 100)
    app = fclient.app
    payment_flow.reconcile_pending(app.state.db, app.state.flw, app.state.events)     # the sweeper runs this BEFORE expiry
    assert order_row(fclient, o["id"]) == ("confirmed", "paid")


# --------------------------------------------------------------------------------------------- client + config
def test_client_errors_never_leak_the_key():
    def boom(request):
        raise httpx.ConnectError("secret=" + KEY)
    c = FlutterwaveClient(KEY, transport=httpx.MockTransport(boom))
    with pytest.raises(FlutterwaveError) as e:
        c.verify_by_reference("PAY-AAAAAAAA")
    assert KEY not in str(e.value)


def test_client_rejects_a_non_https_link():
    c = FlutterwaveClient(KEY, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"status": "success", "data": {"link": "http://evil.example/x"}})))
    with pytest.raises(FlutterwaveError):
        c.create_link(tx_ref="PAY-AAAAAAAA", amount_cents=100, currency="ZMW", redirect_url="https://a.b", email="a@b.co",
                      name="A B", phone="+260971234567", title="Shop", payment_options="card")


def test_plain_http_links_are_accepted_only_from_a_plain_http_test_double():
    reply = lambda r: httpx.Response(200, json={"status": "success", "data": {"link": "http://127.0.0.1:9/pay/x"}})   # noqa: E731
    args = dict(tx_ref="PAY-AAAAAAAA", amount_cents=100, currency="ZMW", redirect_url="https://a.b", email="a@b.co",
                name="A B", phone="+260971234567", title="Shop", payment_options="card")
    local = FlutterwaveClient(KEY, base_url="http://127.0.0.1:9/v3", transport=httpx.MockTransport(reply))
    assert local.create_link(**args).startswith("http://127.0.0.1")
    real = FlutterwaveClient(KEY, transport=httpx.MockTransport(reply))                    # the real https base URL
    with pytest.raises(FlutterwaveError):
        real.create_link(**args)


def test_database_url_from_render_is_given_the_driver_name():
    for given in ("postgres://u:p@h/db", "postgresql://u:p@h/db"):
        assert Settings(database_url=given, _env_file=None).app_database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="sqlite:///x.db", _env_file=None).app_database_url == "sqlite:///x.db"


def test_production_refuses_unsafe_settings_and_accepts_safe_ones():
    bad = Settings(environment="production", _env_file=None)
    problems = " ".join(bad.production_problems())
    for word in ("SUPABASE_URL", "DATABASE_URL", "PAYMENTS_SIMULATED_ENABLED", "DOCS_ENABLED", "CORS_ORIGINS", "SEED_DEMO_DATA", "STORE_IS_DEMO", "STORE_CONTACT_EMAIL"):
        assert word in problems
    assert any("LOCAL_AUTH_ENABLED" in p for p in Settings(local_auth_enabled=True, _env_file=None).production_problems())
    good = Settings(environment="production", supabase_url="https://abc.supabase.co", database_url="postgresql://u:p@h/db",
                    payments_simulated_enabled=False, docs_enabled=False, cors_origins="https://shop.example.com",
                    seed_demo_data=False, store_is_demo=False, store_contact_email="shop@example.com",
                    flw_secret_key="FLWSECK-live", flw_webhook_hash="h", _env_file=None)
    assert good.production_problems() == []
    assert any("FLW_WEBHOOK_HASH" in p for p in Settings(flw_secret_key="FLWSECK-x", _env_file=None).production_problems())


def test_app_refuses_to_start_in_production_with_unsafe_settings(settings):
    settings.environment = "production"
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        with TestClient(create_app(settings)):
            pass


def test_the_payment_page_can_poll_every_five_seconds_without_being_rate_limited(flw_settings, fake):
    flw_settings.checkout_rate_limit_per_min = 10          # the strict default for placing orders
    with TestClient(create_app(flw_settings, flw=FlutterwaveClient(KEY, transport=httpx.MockTransport(fake.handler)))) as c:
        h = cust()
        _, ref = place(c, h)
        codes = [c.post(f"/payments/{ref}/verify", headers=h).status_code for _ in range(30)]     # 2.5 minutes of polling
        assert set(codes) == {200}


def test_cancelled_attempts_are_rechecked_for_a_while_in_case_the_customer_paid_late(fclient, fake):
    h = cust()
    o, ref = place(fclient, h)
    with fclient.app.state.db.session() as s:
        s.get(Order, o["id"]).payment_due_at = utcnow() - timedelta(minutes=1)
        s.scalar(select(PaymentAttempt).where(PaymentAttempt.reference == ref)).created_at = utcnow() - timedelta(minutes=45)
    app = fclient.app
    with app.state.db.session() as s:
        from app.services.order_service import expire_unpaid_orders
        expire_unpaid_orders(s)                                    # what the sweeper does after the hold ends
    assert order_row(fclient, o["id"]) == ("cancelled", "cancelled")
    fake.pay(ref, o["total_cents"] / 100)                           # the customer paid on the page they left open; the webhook was lost
    assert payment_flow.reconcile_pending(app.state.db, app.state.flw, app.state.events) == 1
    assert order_row(fclient, o["id"]) == ("cancelled", "refund_pending")
    assert payment_flow.reconcile_pending(app.state.db, app.state.flw, app.state.events) == 0   # settled: no longer polled
