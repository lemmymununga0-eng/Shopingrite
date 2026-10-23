"""Customer e-mails (order confirmed, progress updates, cancellation, refund) over plain SMTP.

Design rules, each covered by a test:
  * Nothing is sent unless SMTP_HOST and SMTP_FROM are configured; the store works the same without e-mail.
  * A message is queued inside the database transaction but only SENT after that transaction commits, so a rolled-back
    checkout never e-mails anyone.
  * Sending happens on a small background pool and can never fail or slow a request; failures are only logged.
  * Messages are plain text, contain no card or payment secrets, and header values are stripped of line breaks.
"""
import logging
import re
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.message import EmailMessage

log = logging.getLogger("fraudguard")
_NEWLINES = re.compile(r"[\r\n]+")


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str


def smtp_sender(s):
    """A function that delivers one Message with the SMTP settings in `s`."""
    def send(m: Message) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, m.to, _NEWLINES.sub(" ", m.subject)[:200]
        msg.set_content(m.body)
        if s.smtp_port == 465:
            client = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
        with client:
            if s.smtp_port != 465 and s.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                client.login(s.smtp_user, s.smtp_password)
            client.send_message(msg)
    return send


class Notifier:
    def __init__(self, settings, sender=None):
        self.s = settings
        self.enabled = bool(settings.smtp_host.strip() and settings.smtp_from.strip())
        self._send = sender or (smtp_sender(settings) if self.enabled else None)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mail") if self._send else None
        if sender is not None:
            self.enabled = True

    def deliver(self, m: Message, wait: bool = False) -> None:
        if not self.enabled or self._pool is None:
            return
        fut = self._pool.submit(self._safe, m)
        if wait:
            fut.result(timeout=30)

    def _safe(self, m: Message) -> None:
        try:
            self._send(m)
        except Exception as exc:         # never let mail trouble reach a customer's request
            log.warning("e-mail to a customer could not be sent: %s", type(exc).__name__)

    def flush(self) -> None:
        """Wait until every message handed over so far has been attempted (used by tests and on shutdown)."""
        if self._pool is not None:
            self._pool.submit(lambda: None).result(timeout=30)

    def close(self) -> None:
        if self._pool:
            self._pool.shutdown(wait=False)


# ------------------------------------------------------------------------------------------------ queueing
def queue(session, message: Message) -> None:
    """Remember a message to send once this session's transaction commits (Database.session runs the queue)."""
    session.info.setdefault("after_commit", []).append(message)


def queue_status(session, order, new_status: str) -> None:
    """Queue the customer's e-mail for an order status change (no-op when e-mail is not configured)."""
    notifier = session.info.get("notifier")
    if notifier is None or not notifier.enabled:
        return
    s = notifier.s
    contact = " · ".join(x for x in (s.store_contact_phone, s.store_contact_email) if x)
    m = for_status(order, new_status, s.store_name, contact)
    if m is not None:
        queue(session, m)


def queue_refund(session, order) -> None:
    notifier = session.info.get("notifier")
    if notifier is not None and notifier.enabled:
        queue(session, for_refund(order, notifier.s.store_name))


def _money(cents: int, currency: str) -> str:
    return f"{currency} {cents / 100:,.2f}"


def _items(order) -> str:
    return "\n".join(f"  {i.quantity} x {i.name_snapshot}  {_money(i.line_total_cents, order.currency)}" for i in order.items)


def _how_paid(order) -> str:
    if order.payment_status == "cod_due":
        return "Payment: cash on delivery. Please pay the courier when your order arrives."
    if order.payment_status == "paid":
        return "Payment: received. Thank you."
    return ""


def _delivery(order) -> str:
    if order.fulfilment == "delivery":
        return f"Delivery to: {order.address_line}, {order.city}"
    return "Collection: you will collect this order from the store."


def for_status(order, new_status: str, store_name: str, contact: str = "") -> Message | None:
    """The e-mail (if any) a customer should get when their order moves to `new_status`."""
    ref, to = order.reference, order.contact_email
    sign = f"\n\n{store_name}" + (f"\n{contact}" if contact else "")
    if new_status == "confirmed":
        body = (f"Hello {order.contact_name},\n\nYour order {ref} is confirmed.\n\n{_items(order)}\n\n"
                f"Delivery: {_money(order.delivery_fee_cents, order.currency)}\nTotal: {_money(order.total_cents, order.currency)}\n"
                f"{_how_paid(order)}\n{_delivery(order)}\n\nYou can follow your order under 'My orders' on our website.{sign}")
        return Message(to, f"Order {ref} confirmed", body)
    texts = {
        "picking": ("is being prepared", "We have started preparing your order."),
        "ready": ("is ready", "Your order is ready." + (" Please come and collect it." if order.fulfilment == "collection" else " It will go out for delivery soon.")),
        "out_for_delivery": ("is on its way", "Your order is out for delivery."),
        "completed": ("is complete", "Your order is complete. Thank you for shopping with us."),
        "cancelled": ("was cancelled", "Your order was cancelled and the items were released."
                      " If you had already paid, we will refund the full amount to the account you paid from; this can take several days."),
    }
    if new_status not in texts:
        return None
    head, line = texts[new_status]
    return Message(to, f"Order {ref} {head}", f"Hello {order.contact_name},\n\n{line}\n\nOrder: {ref}\nTotal: {_money(order.total_cents, order.currency)}{sign}")


def for_refund(order, store_name: str) -> Message:
    return Message(order.contact_email, f"Refund for order {order.reference}",
                   f"Hello {order.contact_name},\n\nWe have refunded {_money(order.total_cents, order.currency)} for order {order.reference} "
                   f"to the account you paid from. Depending on your bank or mobile-money provider it can take several days to show.\n\n{store_name}")
