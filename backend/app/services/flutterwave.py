"""Flutterwave v3 client (hosted checkout, verification, refunds).

Why hosted checkout: the customer enters card or mobile-money details on Flutterwave's own page, so this server never
sees card numbers, PINs or OTPs. All we hold is a payment reference (`tx_ref`, our PAY-XXXXXXXX), a hosted link and
Flutterwave's transaction id.

Trust rules (from Flutterwave's documentation):
  * The redirect back to the store and the webhook only TELL us a payment may have finished. Value is given only after
    `verify_by_reference` returns status "successful" with our reference, our currency and an amount >= the order's.
  * The secret key lives in the environment (FLW_SECRET_KEY), is sent only as a Bearer header, and is never logged.

Test mode and live mode use the same base URL; the key prefix (FLWSECK_TEST-...) decides.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx


class FlutterwaveError(Exception):
    """Flutterwave could not be reached or refused the call. The message is safe to show to staff, never the key."""


@dataclass(frozen=True)
class Verification:
    state: str                      # successful | failed | pending | not_found
    tx_ref: str = ""
    amount: Decimal = Decimal(0)
    currency: str = ""
    transaction_id: str = ""        # Flutterwave's numeric id (needed for refunds)
    payment_type: str = ""
    processor_response: str = ""


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


class FlutterwaveClient:
    def __init__(self, secret_key: str, base_url: str = "https://api.flutterwave.com/v3", timeout: float = 15.0,
                 transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                                  headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"})

    def _call(self, method: str, path: str, **kw) -> tuple[int, dict]:
        try:
            r = self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:      # the message of httpx errors can contain the URL, never the key
            raise FlutterwaveError("Flutterwave could not be reached (" + type(exc).__name__ + ").") from None
        try:
            body = r.json()
        except ValueError:
            body = {}
        return r.status_code, body if isinstance(body, dict) else {}

    def create_link(self, *, tx_ref: str, amount_cents: int, currency: str, redirect_url: str, email: str, name: str,
                    phone: str, title: str, payment_options: str) -> str:
        """Ask for a hosted payment page and return its URL."""
        payload = {
            "tx_ref": tx_ref, "amount": float(Decimal(amount_cents) / 100), "currency": currency,
            "redirect_url": redirect_url, "payment_options": payment_options,
            "customer": {"email": email, "name": name, "phonenumber": phone},
            "customizations": {"title": title[:60]},
        }
        code, body = self._call("POST", "/payments", json=payload)
        link = (body.get("data") or {}).get("link") if isinstance(body.get("data"), dict) else None
        # The real service only ever returns https links. Plain http is accepted only when the API base itself is plain
        # http, which can only be a local test double (browser tests), never the real Flutterwave.
        schemes = ("https://", "http://") if self._http.base_url.scheme == "http" else ("https://",)
        if code != 200 or body.get("status") != "success" or not isinstance(link, str) or not link.startswith(schemes):
            raise FlutterwaveError(f"Flutterwave refused to create the payment page (HTTP {code}): "
                                   f"{str(body.get('message', 'no message'))[:120]}")
        return link

    def verify_by_reference(self, tx_ref: str) -> Verification:
        code, body = self._call("GET", "/transactions/verify_by_reference", params={"tx_ref": tx_ref})
        data = body.get("data")
        if not isinstance(data, dict):
            msg = str(body.get("message", ""))
            if "no transaction" in msg.lower() or code == 404:
                return Verification("not_found")
            raise FlutterwaveError(f"Flutterwave could not verify the payment (HTTP {code}): {msg[:120]}")
        if code != 200 or body.get("status") != "success":
            raise FlutterwaveError(f"Flutterwave could not verify the payment (HTTP {code}).")
        raw = str(data.get("status", "")).lower()
        state = "successful" if raw == "successful" else "failed" if raw == "failed" else "pending"
        return Verification(state=state, tx_ref=str(data.get("tx_ref", "")), amount=_decimal(data.get("amount", 0)),
                            currency=str(data.get("currency", "")).upper(), transaction_id=str(data.get("id", "")),
                            payment_type=str(data.get("payment_type", ""))[:30],
                            processor_response=str(data.get("processor_response", ""))[:120])

    def refund(self, transaction_id: str, amount_cents: int | None = None, comments: str = "") -> dict:
        """Refund a successful transaction (full when amount_cents is None). Returns Flutterwave's `data`."""
        payload: dict = {}
        if amount_cents is not None:
            payload["amount"] = float(Decimal(amount_cents) / 100)
        if comments:
            payload["comments"] = comments[:120]
        code, body = self._call("POST", f"/transactions/{transaction_id}/refund", json=payload)
        if code != 200 or body.get("status") != "success":
            raise FlutterwaveError(f"Flutterwave refused the refund (HTTP {code}): {str(body.get('message', ''))[:120]}")
        return body.get("data") if isinstance(body.get("data"), dict) else {}

    def close(self):
        self._http.close()


def build_client(settings) -> FlutterwaveClient | None:
    if not settings.flutterwave_enabled:
        return None
    return FlutterwaveClient(settings.flw_secret_key.strip(), settings.flw_base_url, settings.flw_timeout_seconds)
