"""Payment endpoints: available methods, one attempt's status, the controlled demo resolver, Flutterwave real payments
(hosted checkout link, verify on return, cancel, webhook, staff refund) and a signed simulated webhook."""
import hmac
import json
import logging
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth import User, require
from ..db.models import Order, PaymentAttempt, PaymentEvent
from ..dependencies import correlation, limited
from ..schemas.store import PaymentAttemptOut
from ..services import order_service, payment_flow
from ..services import payment_service as pay
from ..services.flutterwave import FlutterwaveError

log = logging.getLogger("fraudguard")
router = APIRouter(tags=["payments"])
_REF = re.compile(r"^PAY-[0-9A-F]{8}$")


class SimulateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["succeeded", "failed", "cancelled"]


class WebhookBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=6, max_length=80)
    payment_reference: str
    outcome: Literal["succeeded", "failed", "cancelled", "pending", "requires_action"]


def _attempt(session, reference: str) -> PaymentAttempt:
    if not _REF.match(reference):
        raise HTTPException(404, "Payment not found")
    a = session.scalar(select(PaymentAttempt).where(PaymentAttempt.reference == reference))
    if a is None:
        raise HTTPException(404, "Payment not found")
    return a


def _visible(session, a: PaymentAttempt, user: User):
    order = order_service.get_order(session, a.order_id)
    # Same 404 for "missing" and "someone else's": a reference reveals nothing.
    if order is None or (order.user_id != user.id and not user.has("orders.view_all")):
        raise HTTPException(404, "Payment not found")
    return order


@router.get("/payments/methods")
def payment_methods(request: Request):
    return {"currency": request.app.state.settings.store_currency, "methods": pay.methods(request.app.state.settings)}


@router.get("/payments/{reference}", response_model=PaymentAttemptOut)
def read_payment(reference: str, request: Request, user: User = Depends(require("store.shop"))):
    with request.app.state.db.session() as session:
        a = _attempt(session, reference)
        _visible(session, a, user)
        return order_service.attempt_out(a)


@router.post("/payments/{reference}/simulate",
             dependencies=[Depends(limited("checkout", "checkout_rate_limit_per_min"))])
def simulate_result(reference: str, body: SimulateBody, request: Request, user: User = Depends(require("store.shop"))):
    """The controlled demonstration: the customer who owns a pending SIMULATED payment resolves it. Refused for any
    other provider, for other customers, and when simulated payments are switched off."""
    s = request.app.state.settings
    if not s.payments_simulated_enabled:
        raise HTTPException(503, "Simulated payments are switched off on this server.")
    with request.app.state.db.session() as session:
        a = _attempt(session, reference)
        order = _visible(session, a, user)
        if order.user_id != user.id or a.provider != "simulated":
            raise HTTPException(404, "Payment not found")
        order_service.expire_unpaid_orders(session)
        session.refresh(a)
        if a.status not in ("pending", "requires_action"):
            raise HTTPException(409, f"This payment is '{a.status}' and can no longer be changed.")
        order_service.apply_outcome(session, order, a, body.outcome, actor_id=user.id,
                                    failure_reason="Simulated: chosen by the demo customer.", correlation_id=correlation(request))
        return {"attempt": order_service.attempt_out(a), "order": order_service.order_view(session, order)}


# ------------------------------------------------------------------ real payments (Flutterwave hosted checkout)
def _flw(request: Request):
    return payment_flow.require_client(getattr(request.app.state, "flw", None))


def _owned_flw_attempt(request: Request, reference: str, user: User) -> None:
    """404 unless this is the caller's own Flutterwave attempt (same 404 as 'missing')."""
    with request.app.state.db.session() as session:
        a = _attempt(session, reference)
        order = _visible(session, a, user)
        if order.user_id != user.id or a.provider != "flutterwave":
            raise HTTPException(404, "Payment not found")


@router.post("/payments/{reference}/checkout-link",
             dependencies=[Depends(limited("checkout", "checkout_rate_limit_per_min"))])
def checkout_link(reference: str, request: Request, user: User = Depends(require("store.shop"))):
    """The page where the customer pays (card or mobile money). Flutterwave collects the details, not this server."""
    _attempt_ref_ok(reference)
    flw = _flw(request)
    return {"url": payment_flow.create_checkout_link(request.app.state.db, flw, request.app.state.settings, reference, user.id)}


@router.post("/payments/{reference}/verify",
             dependencies=[Depends(limited("paycheck", "payment_check_rate_limit_per_min"))])
def verify_payment(reference: str, request: Request, user: User = Depends(require("store.shop"))):
    """Called when the customer comes back from the payment page. The result comes from Flutterwave's API, never from
    the URL the customer returned on."""
    _attempt_ref_ok(reference)
    _owned_flw_attempt(request, reference, user)
    try:
        outcome = payment_flow.verify_and_settle(request.app.state.db, _flw(request), request.app.state.events, reference,
                                                 correlation(request), settings=request.app.state.settings)
    except FlutterwaveError as exc:
        log.warning("verify %s failed: %s", reference, exc)
        raise HTTPException(502, "We could not confirm the payment with the payment provider yet. Please refresh in a moment.")
    return _result(request, reference, outcome)


@router.post("/payments/{reference}/cancel",
             dependencies=[Depends(limited("paycheck", "payment_check_rate_limit_per_min"))])
def cancel_payment(reference: str, request: Request, user: User = Depends(require("store.shop"))):
    """The customer gave up on the payment page. Cancels the attempt only if no payment actually went through."""
    _attempt_ref_ok(reference)
    _owned_flw_attempt(request, reference, user)
    try:
        outcome = payment_flow.cancel_attempt(request.app.state.db, _flw(request), request.app.state.events, reference,
                                              user.id, correlation(request), settings=request.app.state.settings)
    except FlutterwaveError as exc:
        log.warning("cancel %s failed: %s", reference, exc)
        raise HTTPException(502, "We could not check the payment with the payment provider yet. Please try again.")
    return _result(request, reference, outcome)


def _attempt_ref_ok(reference: str) -> None:
    if not _REF.match(reference):
        raise HTTPException(404, "Payment not found")


def _result(request: Request, reference: str, outcome: str) -> dict:
    with request.app.state.db.session() as session:
        a = _attempt(session, reference)
        return {"outcome": outcome, "attempt": order_service.attempt_out(a),
                "order": order_service.order_view(session, order_service.get_order(session, a.order_id))}


@router.post("/payments/webhooks/flutterwave")
async def flutterwave_webhook(request: Request, verif_hash: str | None = Header(default=None)):
    """Flutterwave's 'charge.completed' callback. Authenticated by the shared secret hash in the `verif-hash` header;
    the payload is then only used to find our reference, and the real result is fetched from Flutterwave's API.
    Always 200 for events that are not ours (so Flutterwave stops retrying); 401 for a bad secret; 502 when Flutterwave
    cannot be reached (so it retries)."""
    s = request.app.state.settings
    secret = s.flw_webhook_hash
    if not secret or not verif_hash or not hmac.compare_digest(secret.encode(), verif_hash.strip().encode()):
        request.app.state.events.record("medium", "provider", "payment.webhook_bad_signature",
                                        "A Flutterwave webhook arrived with a missing or invalid secret hash.",
                                        path=request.url.path, method="POST", status_code=401,
                                        correlation_id=correlation(request), dedupe=True)
        raise HTTPException(401, "Invalid signature")
    try:
        body = json.loads(await request.body())
        data = body["data"]
        reference, txn_id, status = str(data["tx_ref"]), str(data["id"]), str(data.get("status", ""))
        event_name = str(body.get("event", "charge.completed"))
    except Exception:
        return {"status": "ignored"}
    if not _REF.match(reference):
        return {"status": "ignored"}              # not one of our payments (the account may serve other apps)
    flw = getattr(request.app.state, "flw", None)
    if flw is None:
        raise HTTPException(503, "Online payments are not configured.")
    try:
        outcome = await run_in_threadpool(
            payment_flow.verify_and_settle, request.app.state.db, flw, request.app.state.events, reference,
            correlation(request), {"id": f"{event_name}:{txn_id}:{status}"[:80], "outcome": status},
            request.app.state.settings)
    except FlutterwaveError as exc:
        log.warning("webhook verify %s failed: %s", reference, exc)
        raise HTTPException(502, "Could not verify with Flutterwave")
    return {"status": "ok", "outcome": outcome}


@router.post("/orders/{order_id}/refund", dependencies=[Depends(limited("checkout", "checkout_rate_limit_per_min"))])
def refund_order(order_id: str, request: Request, user: User = Depends(require("orders.manage"))):
    """Staff: refund the customer for a paid order that was cancelled (payment status 'refund_pending')."""
    try:
        oid = str(uuid.UUID(order_id))
    except ValueError:
        raise HTTPException(404, "Order not found")
    return payment_flow.refund_order(request.app.state.db, _flw(request), oid, user, correlation(request))


@router.post("/payments/webhooks/simulated")
async def simulated_webhook(request: Request, x_signature: str | None = Header(default=None)):
    """Signed provider-style callback. 401 for a bad signature, 200 + duplicate for a repeated event."""
    s = request.app.state.settings
    raw = await request.body()
    if not pay.verify_signature(s.payment_webhook_secret, raw, x_signature):
        request.app.state.events.record("medium", "provider", "payment.webhook_bad_signature",
                                        "A payment webhook arrived with a missing or invalid signature.",
                                        path=request.url.path, method="POST", status_code=401,
                                        correlation_id=correlation(request), dedupe=True)
        raise HTTPException(401, "Invalid signature")
    try:
        body = WebhookBody.model_validate(json.loads(raw))
    except Exception:
        raise HTTPException(422, "Invalid webhook body")
    with request.app.state.db.session() as session:
        a = _attempt(session, body.payment_reference)
        if a.provider != "simulated":
            raise HTTPException(404, "Payment not found")
        session.add(PaymentEvent(attempt_id=a.id, provider="simulated", event_id=body.event_id, outcome=body.outcome,
                                 signature_valid=True))
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return {"status": "duplicate", "applied": False}
        order = order_service.get_order(session, a.order_id)
        applied = order_service.apply_outcome(session, order, a, body.outcome, correlation_id=correlation(request))
        ev = session.scalar(select(PaymentEvent).where(PaymentEvent.provider == "simulated",
                                                       PaymentEvent.event_id == body.event_id))
        ev.applied = applied
        return {"status": "ok", "applied": applied, "payment_status": a.status}
