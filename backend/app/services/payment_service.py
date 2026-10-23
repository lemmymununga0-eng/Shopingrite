"""Payment provider layer.

* SIMULATED: a clearly labelled demonstration provider. The customer picks the outcome (success, failure, pending,
  cancelled, action required) in a controlled demo. It never receives card numbers, PINs or one-time codes: the API
  schema has no field for them. No bank or mobile-money network is contacted and no money moves.
* COD (cash on delivery): only when an administrator enables it (COD_ENABLED).
* Airtel Money, MTN Mobile Money and Visa/Mastercard: real payments through Flutterwave's hosted checkout
  (services/flutterwave.py). They are offered only when FLW_SECRET_KEY is set; otherwise choosing one is refused before
  stock is touched. Creating an order never calls the network: the attempt starts 'pending' and the hosted link is
  requested afterwards (routers/payments.py), so no database transaction is held open during an HTTP call.

Adding another provider means writing one class with `initiate()` and registering it here; checkout, order states and
fraud assessment do not change.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass

SCENARIOS = ("success", "failure", "pending", "cancelled", "action_required")
METHODS = ("simulated", "cod", "airtel_money", "mtn_momo", "card")
# Methods that go through Flutterwave's hosted checkout, and the `payment_options` value each one asks for.
ONLINE = {"airtel_money": "Airtel Money", "mtn_momo": "MTN Mobile Money", "card": "Visa / Mastercard"}
FLW_OPTIONS = {"airtel_money": "mobilemoneyzambia", "mtn_momo": "mobilemoneyzambia", "card": "card"}
LABELS = {"simulated": "Simulated payment (demonstration)", "cod": "Cash on delivery", **ONLINE}

SIM_NOTICE = ("DEMONSTRATION PAYMENT: this is a simulated checkout. No card or mobile-money account was used and no "
              "money was taken or authorised by any bank or network.")
COD_NOTICE = "Cash on delivery: pay the courier when the order arrives. No payment has been taken yet."
TEST_NOTICE = ("TEST MODE: payments are processed by the payment provider's test environment. No real money is taken "
               "and no real mobile-money or card account is charged.")


class PaymentUnavailable(Exception):
    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


@dataclass(frozen=True)
class ProviderResult:
    status: str                 # attempt status: pending | requires_action | succeeded | failed | cancelled
    provider_reference: str
    failure_reason: str = ""


def new_payment_reference() -> str:
    return "PAY-" + secrets.token_hex(4).upper()


class SimulatedProvider:
    name, mode = "simulated", "SIMULATED"
    _MAP = {"success": ("succeeded", ""), "failure": ("failed", "Simulated decline: the demo customer chose failure."),
            "pending": ("pending", ""), "cancelled": ("cancelled", "Simulated: the customer cancelled the payment."),
            "action_required": ("requires_action", "")}

    def initiate(self, *, reference: str, amount_cents: int, currency: str, scenario: str) -> ProviderResult:
        status, reason = self._MAP[scenario]
        return ProviderResult(status=status, provider_reference="SIM-" + secrets.token_hex(5).upper(), failure_reason=reason)


class CashOnDeliveryProvider:
    name, mode = "cod", "COD"

    def initiate(self, *, reference: str, amount_cents: int, currency: str, scenario: str) -> ProviderResult:
        return ProviderResult(status="pending", provider_reference="COD-" + reference)


class FlutterwaveProvider:
    """Hosted checkout. `initiate` makes no network call: the attempt is 'pending' until the customer has paid on
    Flutterwave's page and we have verified the result with Flutterwave's API."""
    name = "flutterwave"

    def __init__(self, test_mode: bool):
        self.mode = "TEST" if test_mode else "LIVE"

    def initiate(self, *, reference: str, amount_cents: int, currency: str, scenario: str) -> ProviderResult:
        return ProviderResult(status="pending", provider_reference="")


PROVIDERS = {"simulated": SimulatedProvider(), "cod": CashOnDeliveryProvider()}


def provider_for(method: str, settings):
    """The provider for a method, or PaymentUnavailable (raised BEFORE any stock is reserved)."""
    if method in ONLINE:
        if not settings.flutterwave_enabled:
            raise PaymentUnavailable("provider_not_configured",
                                     f"{ONLINE[method]} is not available right now. Please choose another payment method.")
        return FlutterwaveProvider(settings.flutterwave_test_mode)
    if method == "cod" and not settings.cod_enabled:
        raise PaymentUnavailable("cod_disabled", "Cash on delivery is not enabled for this store.", 422)
    if method == "simulated" and not settings.payments_simulated_enabled:
        raise PaymentUnavailable("simulated_disabled", "Simulated payments are switched off on this server.")
    return PROVIDERS[method]


def methods(settings) -> list[dict]:
    out = [{"id": "simulated", "label": LABELS["simulated"], "available": settings.payments_simulated_enabled,
            "mode": "SIMULATED", "reason": "" if settings.payments_simulated_enabled else "Switched off on this server.",
            "scenarios": list(SCENARIOS)},
           {"id": "cod", "label": LABELS["cod"], "available": settings.cod_enabled, "mode": "COD",
            "reason": "" if settings.cod_enabled else "Not enabled by the store administrator.", "scenarios": []}]
    online_mode = "TEST" if settings.flutterwave_test_mode else "LIVE"
    out += [{"id": k, "label": v, "available": settings.flutterwave_enabled, "mode": online_mode, "scenarios": [],
             "reason": "" if settings.flutterwave_enabled else "Not available right now."} for k, v in ONLINE.items()]
    return out


def notice_for(mode: str) -> str:
    return {"SIMULATED": SIM_NOTICE, "COD": COD_NOTICE, "TEST": TEST_NOTICE}.get(mode, "")


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Constant-time check. An empty secret means webhooks are switched off, never 'accept everything'."""
    if not secret or not signature:
        return False
    return hmac.compare_digest(sign(secret, body), signature.strip().lower())
