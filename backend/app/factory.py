"""Application factory: builds the FastAPI app so tests can create isolated instances."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import BACKEND_DIR, Settings, get_settings
from .core.security import client_hash, correlation_id, resolve_local_secret
from .db.seed import (convert_demo_currency, convert_demo_images, retire_legacy_demo, seed_catalogue, seed_demo_users,
                      seed_zambian_catalogue)
from .db.app_repo import AppRepository
from .db.session import Database
from .db.sqlite_repo import SqliteRepository
from .db.supabase_repo import SupabaseRepository
from .dependencies import RateLimiter
from .ml.pca_demo import PcaPredictor
from .ml.predict import Predictor
from .ml.service import ModelService
from .routers import (fraud as fraud_router, admin, auth_local, cart, inventory, investigations, orders, pca_demo as pca_router, products,
                      reports, scamwatch, security, system, transactions, payments, staff_orders, catalogue_admin)
from .services.flutterwave import build_client as build_flw_client
from .services.notifications import Notifier
from .services.scamwatch_service import MlUrlProvider, build_providers
from .services.security_events import SecurityEvents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)   # request URLs can contain API keys; never log them
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("fraudguard")


class BodyLimitMiddleware:
    """Counts the bytes actually received, so a chunked upload without a Content-Length header cannot get past
    the limit (the header check in `observe` only catches honest clients). Once the limit is passed the app is
    shown an empty end of body, and whatever it answers is replaced by 413."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        total, too_large, replied = 0, False, False

        async def limited_receive():
            nonlocal total, too_large
            if too_large:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def replacing_send(message):
            nonlocal replied
            if not too_large:
                return await send(message)
            if not replied:
                replied = True
                body = b'{"detail":"Request body too large"}'
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})

        await self.app(scope, limited_receive, replacing_send)


def build_repo(s: Settings, db: Database | None = None):
    if s.db_backend == "app":
        return AppRepository(db)       # the application database: durable on a host with PostgreSQL
    if s.db_backend == "supabase":
        return SupabaseRepository(s.supabase_url, s.supabase_anon_key)
    if s.db_backend == "sqlite":
        return SqliteRepository(s.sqlite_path)
    raise RuntimeError(f"Unknown DB_BACKEND '{s.db_backend}' (use 'app', 'sqlite' or 'supabase')")


EXPIRY_SWEEP_SECONDS = 60


def _expire_now(app) -> int:
    from .services.order_service import expire_unpaid_orders
    with app.state.db.session() as session:
        return expire_unpaid_orders(session)


def _reconcile_now(app) -> int:
    from .services.payment_flow import reconcile_pending
    flw = getattr(app.state, "flw", None)
    return reconcile_pending(app.state.db, flw, app.state.events, settings=app.state.settings) if flw is not None else 0


async def _expiry_sweeper(app):
    """Every minute: settle online payments whose webhook never arrived, then release stock held by orders whose
    payment window has ended (in that order, so a customer who paid just before the deadline is not expired).
    Failures are logged, never fatal."""
    while True:
        await asyncio.sleep(EXPIRY_SWEEP_SECONDS)
        try:
            c = await run_in_threadpool(_reconcile_now, app)
            if c:
                log.info("reconciled %s online payment(s)", c)
        except Exception:
            log.exception("payment reconcile failed")
        try:
            n = await run_in_threadpool(_expire_now, app)
            if n:
                log.info("released %s expired unpaid order(s)", n)
        except Exception:
            log.exception("expiry sweep failed")


def create_app(settings: Settings | None = None, repo=None, predictor: Predictor | None = None,
               db: Database | None = None, providers: list | None = None, flw=None, notifier=None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if s.environment.lower() == "production":
            problems = s.production_problems()
            if problems:
                raise RuntimeError("Unsafe production configuration:\n  - " + "\n  - ".join(problems))
        if s.local_auth_enabled:
            if s.environment.lower() == "production":
                raise RuntimeError("LOCAL_AUTH_ENABLED must not be used with ENVIRONMENT=production.")
            s.local_auth_secret = resolve_local_secret(s.local_auth_secret, BACKEND_DIR / "data")
            log.warning("LOCAL DEMO AUTH IS ENABLED. Do not expose this server to other people.")
        app.state.settings = s
        app.state.db = db or Database(s.app_database_url)
        app.state.db.create_all()
        app.state.db.notifier = notifier if notifier is not None else Notifier(s)
        log.info("customer e-mail: %s", "on" if app.state.db.notifier.enabled else "off (SMTP not configured)")
        app.state.repo = repo or build_repo(s, app.state.db)
        app.state.events = SecurityEvents(app.state.db)
        app.state.events.seed_thresholds()
        if s.seed_demo_data:
            with app.state.db.session() as session:
                added = seed_zambian_catalogue(session, s.store_currency) if s.seed_zm_catalogue else {}
                if s.seed_legacy_demo:
                    added.update(seed_catalogue(session, s.store_currency))
                    added["currency_converted"] = convert_demo_currency(session, s.store_currency)
                    added["images_converted"] = convert_demo_images(session)
                else:
                    added["legacy_retired"] = retire_legacy_demo(session)
                if s.local_auth_enabled:
                    added["demo_users"] = seed_demo_users(session)
            if any(added.values()):
                log.info("seeded demonstration data: %s", added)
        app.state.providers = providers if providers is not None else build_providers(s)
        app.state.flw = flw if flw is not None else build_flw_client(s)
        log.info("online payments: %s", ("Flutterwave " + ("TEST" if s.flutterwave_test_mode else "LIVE"))
                 if app.state.flw is not None else "not configured")
        if predictor is None:
            p = Predictor(s.risk_high, s.risk_medium, s.model_threshold)
            p.load(s.model_path)
            app.state.predictor = p
        else:
            app.state.predictor = predictor
        app.state.pca = PcaPredictor(s.risk_high, s.risk_medium, s.model_threshold)
        app.state.pca.load(s.pca_model_path)
        app.state.ml = ModelService(s.ml_artifact_dir)
        app.state.ml.load_all()
        app.state.db.ml = app.state.ml
        if providers is None and "ml_url" in s.provider_list:
            app.state.providers.append(MlUrlProvider(app.state.ml))
        app.state.limiter = RateLimiter()
        pr = app.state.predictor
        log.info("model %s", "loaded " + pr.metadata["version"] if pr.available else "NOT loaded: " + pr.error)
        sweeper = asyncio.create_task(_expiry_sweeper(app))
        yield
        sweeper.cancel()
        if app.state.flw is not None:
            app.state.flw.close()
        app.state.db.notifier.close()
        app.state.db.dispose()

    app = FastAPI(title="FraudGuard API", version="3.0.0", lifespan=lifespan,
                  docs_url="/docs" if s.docs_enabled else None, redoc_url=None,
                  openapi_url="/openapi.json" if s.docs_enabled else None,
                  description="Online grocery store with a staff fraud and security console.")
    app.add_middleware(BodyLimitMiddleware, max_bytes=s.max_body_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
                       expose_headers=["X-Request-ID", "Idempotent-Replay"])

    @app.middleware("http")
    async def observe(request: Request, call_next):
        cid = correlation_id(request.headers.get("x-request-id"))
        request.state.correlation_id = cid
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > s.max_body_bytes:
            response = JSONResponse({"detail": "Request body too large"}, status_code=413)
            response.headers["X-Request-ID"] = cid
            await run_in_threadpool(_record, request, 413, ("low", "input", "input.body_too_large",
                                                            "Request body larger than the allowed limit"))
            return response
        response = await call_next(request)
        response.headers["X-Request-ID"] = cid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path not in ("/docs", "/redoc", "/openapi.json"):          # the interactive docs (dev only) need scripts
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if app.state.settings.environment.lower() == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        code = response.status_code
        pending = getattr(request.state, "security_event", None)
        if pending or code in (403, 429):
            await run_in_threadpool(_record, request, code, pending)
        return response

    def _record(request: Request, code: int, pending):
        events = getattr(request.app.state, "events", None)
        if events is None:
            return
        if pending is None:
            if code == 429:
                pending = ("low", "rate_limit", "rate_limit.exceeded", "Rate limit exceeded")
            else:
                pending = ("medium", "authorization", "authz.denied", f"Access denied on {request.url.path}")
        severity, category, event_type, message = pending
        events.record(severity, category, event_type, message, actor_id=getattr(request.state, "user_id", None),
                      client_tag=client_hash(request.client.host if request.client else None),
                      path=request.url.path, method=request.method, status_code=code,
                      correlation_id=getattr(request.state, "correlation_id", None), dedupe=True)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Report where and why, but never echo the submitted values (they may be NaN or sensitive).
        errors = [{"field": ".".join(str(x) for x in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]}
                  for e in exc.errors()]
        events = getattr(request.app.state, "events", None)
        if events is not None:
            await run_in_threadpool(
                events.record, "info", "input", "input.rejected", f"Request rejected by validation on {request.url.path}",
                actor_id=getattr(request.state, "user_id", None),
                client_tag=client_hash(request.client.host if request.client else None), path=request.url.path,
                method=request.method, status_code=422, correlation_id=getattr(request.state, "correlation_id", None),
                details={"fields": [e["field"] for e in errors]}, dedupe=True)
        return JSONResponse({"detail": "Validation failed", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        cid = getattr(request.state, "correlation_id", None)
        events = getattr(request.app.state, "events", None)
        if events is not None:
            await run_in_threadpool(
                events.record, "high", "application", "app.unhandled_exception",
                f"Unhandled {type(exc).__name__} on {request.method} {request.url.path}",
                actor_id=getattr(request.state, "user_id", None), path=request.url.path, method=request.method,
                status_code=500, correlation_id=cid,
                client_tag=client_hash(request.client.host if request.client else None))
        return JSONResponse({"detail": "Internal server error", "correlation_id": cid}, status_code=500,
                            headers={"X-Request-ID": cid or ""})

    for module in (system, auth_local, products, inventory, cart, orders, transactions, pca_router, scamwatch, security,
                   investigations, reports, admin, payments, staff_orders, catalogue_admin, fraud_router):
        app.include_router(module.router)
    return app
