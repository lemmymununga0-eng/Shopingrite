"""Customer e-mails: sent only after commit, never on rollback, never blocking, plain text, header-safe."""
import smtplib
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.factory import create_app
from app.services import notifications as n
from app.services.notifications import Message, Notifier

from .conftest import admin_h, cust, order_body, put_in_cart

SKU = "DEMO-FP-001"


class Outbox:
    def __init__(self):
        self.messages, self.lock, self.fail = [], threading.Lock(), False

    def __call__(self, m: Message):
        if self.fail:
            raise RuntimeError("smtp is down")
        with self.lock:
            self.messages.append(m)


@pytest.fixture()
def outbox():
    return Outbox()


@pytest.fixture()
def mail_client(settings, outbox):
    settings.smtp_host, settings.smtp_from = "smtp.example.test", "shop@example.test"
    settings.store_name = "Mwila Foods"
    notifier = Notifier(settings, sender=outbox)
    with TestClient(create_app(settings, notifier=notifier)) as c:
        c.notifier = notifier
        yield c


def buy(client, h, method="simulated", scenario="success", qty=1, **over):
    put_in_cart(client, h, SKU, qty)
    return client.post("/orders", json=order_body(payment={"method": method, "scenario": scenario}, **over), headers=h)


def sent(client, outbox):
    client.notifier.flush()
    return list(outbox.messages)


def test_a_confirmed_order_sends_one_plain_text_email_to_the_customer(mail_client, outbox):
    r = buy(mail_client, cust())
    o = r.json()
    msgs = sent(mail_client, outbox)
    assert len(msgs) == 1 and msgs[0].to == "shopper@example.com"
    assert msgs[0].subject == f"Order {o['reference']} confirmed"
    body = msgs[0].body
    assert o["reference"] in body and "Test Shopper" in body and "Mwila Foods" in body and "Payment: received" in body
    assert f"ZMW {o['total_cents'] / 100:,.2f}" in body
    for secret in ("card number", "cvv", "pin", "password", "token"):
        assert secret not in body.lower()


def test_cash_on_delivery_email_says_so(settings, outbox):
    settings.cod_enabled, settings.smtp_host, settings.smtp_from = True, "smtp.example.test", "shop@example.test"
    notifier = Notifier(settings, sender=outbox)
    with TestClient(create_app(settings, notifier=notifier)) as c:
        c.notifier = notifier
        buy(c, cust(), method="cod")
        msgs = sent(c, outbox)
    assert len(msgs) == 1 and "cash on delivery" in msgs[0].body.lower()


def test_no_email_for_a_failed_payment_or_a_rejected_checkout(mail_client, outbox):
    assert buy(mail_client, cust(), scenario="failure").status_code == 201
    r = mail_client.post("/orders", json=order_body(payment={"method": "simulated", "scenario": "success"}), headers=cust("cust-3"))
    assert r.status_code == 409                                             # empty cart: nothing was ordered
    assert sent(mail_client, outbox) == []


def test_a_rolled_back_transaction_never_sends(mail_client, outbox):
    db = mail_client.app.state.db
    with pytest.raises(RuntimeError):
        with db.session() as s:
            n.queue(s, Message("a@example.com", "subject", "body"))
            raise RuntimeError("something failed after the message was queued")
    assert sent(mail_client, outbox) == []
    with db.session() as s:
        n.queue(s, Message("a@example.com", "subject", "body"))             # a committed one is sent
    assert [m.subject for m in sent(mail_client, outbox)] == ["subject"]


def test_staff_progress_and_cancellation_emails(mail_client, outbox):
    o = buy(mail_client, cust()).json()
    for status in ("picking", "ready", "out_for_delivery", "completed"):
        r = mail_client.patch(f"/orders/{o['id']}/status", json={"status": status}, headers=admin_h())
        assert r.status_code == 200, r.text
    subjects = [m.subject for m in sent(mail_client, outbox)]
    ref = o["reference"]
    assert subjects == [f"Order {ref} confirmed", f"Order {ref} is being prepared", f"Order {ref} is ready",
                        f"Order {ref} is on its way", f"Order {ref} is complete"]
    o2 = buy(mail_client, cust("cust-2")).json()
    mail_client.post(f"/orders/{o2['id']}/cancel", headers=cust("cust-2"))
    last = sent(mail_client, outbox)[-1]
    assert last.subject == f"Order {o2['reference']} was cancelled" and "refund" in last.body.lower()
    assert last.to == "shopper@example.com"


def test_email_trouble_never_breaks_an_order(mail_client, outbox):
    outbox.fail = True
    r = buy(mail_client, cust())
    assert r.status_code == 201 and r.json()["status"] == "confirmed"
    mail_client.notifier.flush()
    assert outbox.messages == []


def test_nothing_is_sent_and_nothing_breaks_when_smtp_is_not_configured(client):
    assert client.app.state.db.notifier.enabled is False
    r = buy(client, cust())
    assert r.status_code == 201 and r.json()["status"] == "confirmed"


def test_the_smtp_sender_logs_in_uses_tls_and_strips_header_injection(monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls["connect"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            calls["tls"] = True

        def login(self, user, password):
            calls["login"] = (user, password)

        def send_message(self, msg):
            calls["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    s = Settings(smtp_host="smtp.example.test", smtp_port=587, smtp_user="u", smtp_password="p", smtp_from="shop@example.test", _env_file=None)
    n.smtp_sender(s)(Message("a@example.com", "Hello\r\nBcc: attacker@example.com", "body"))
    assert calls["connect"] == ("smtp.example.test", 587) and calls["tls"] and calls["login"] == ("u", "p")
    msg = calls["msg"]
    assert msg["To"] == "a@example.com" and msg["From"] == "shop@example.test" and "\n" not in msg["Subject"] and msg["Bcc"] is None
    assert msg.get_content_type() == "text/plain"


def test_message_builders_cover_every_status_and_ignore_unknown_ones():
    class Item:
        quantity, name_snapshot, line_total_cents = 2, "Bananas", 5000

    class Order:
        reference, contact_name, contact_email, currency = "ORD-1", "Mia", "mia@example.com", "ZMW"
        total_cents, delivery_fee_cents, payment_status = 8500, 3500, "paid"
        fulfilment, address_line, city, items = "delivery", "12 Test Street", "Lusaka", [Item()]

    for status in ("confirmed", "picking", "ready", "out_for_delivery", "completed", "cancelled"):
        m = n.for_status(Order, status, "Shop")
        assert m is not None and m.to == "mia@example.com" and "ORD-1" in m.subject
    assert n.for_status(Order, "awaiting_payment", "Shop") is None and n.for_status(Order, "payment_failed", "Shop") is None
    assert "12 Test Street" in n.for_status(Order, "confirmed", "Shop").body
    assert "refunded ZMW 85.00" in n.for_refund(Order, "Shop").body


def test_refund_sends_a_refund_email(settings, outbox):
    import httpx
    from app.services.flutterwave import FlutterwaveClient
    from .test_flutterwave import HOOK, KEY, FakeFlutterwave
    fake = FakeFlutterwave()
    settings.flw_secret_key, settings.flw_webhook_hash = KEY, HOOK
    settings.smtp_host, settings.smtp_from = "smtp.example.test", "shop@example.test"
    notifier = Notifier(settings, sender=outbox)
    with TestClient(create_app(settings, flw=FlutterwaveClient(KEY, transport=httpx.MockTransport(fake.handler)), notifier=notifier)) as c:
        c.notifier = notifier
        put_in_cart(c, cust(), SKU, 1)
        o = c.post("/orders", json=order_body(payment={"method": "card"}), headers=cust()).json()
        ref = o["payment_attempts"][0]["reference"]
        fake.pay(ref, o["total_cents"] / 100)
        c.post(f"/payments/{ref}/verify", headers=cust())
        c.post(f"/orders/{o['id']}/cancel", headers=cust())
        assert c.post(f"/orders/{o['id']}/refund", headers=admin_h()).status_code == 200
        subjects = [m.subject for m in sent(c, outbox)]
    assert subjects == [f"Order {o['reference']} confirmed", f"Order {o['reference']} was cancelled", f"Refund for order {o['reference']}"]
