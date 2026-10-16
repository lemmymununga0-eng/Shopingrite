"""Application factory: builds the FastAPI app so tests can create isolated instances."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import BACKEND_DIR, Settings, get_settings
from .core.security import client_hash, correlation_id, resolve_local_secret
from .db.seed import seed_catalogue, seed_demo_users
from .db.session import Database
from .db.sqlite_repo import SqliteRepository
from .db.supabase_repo import SupabaseRepository
from .dependencies import RateLimiter
from .ml.pca_demo import PcaPredictor
from .ml.predict import Predictor
from .routers import (admin, auth_local, cart, inventory, investigations, orders, pca_demo as pca_router, products,
                      reports, scamwatch, security, system, transactions)
from .services.scamwatch_service import build_providers
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


def build_repo(s: Settings):
    if s.db_backend == "supabase":
        return SupabaseRepository(s.supabase_url, s.supabase_anon_key)
    if s.db_backend == "sqlite":
        return SqliteRepository(s.sqlite_path)
    raise RuntimeError(f"Unknown DB_BACKEND '{s.db_backend}' (use 'sqlite' or 'supabase')")


def create_app(settings: Settings | None = None, repo=None, predictor: Predictor | None = None,
               db: Database | None = None, providers: list | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if s.local_auth_enabled:
            if s.environment.lower() == "production":
                raise RuntimeError("LOCAL_AUTH_ENABLED must not be used with ENVIRONMENT=production.")
            s.local_auth_secret = resolve_local_secret(s.local_auth_secret, BACKEND_DIR / "data")
            log.warning("LOCAL DEMO AUTH IS ENABLED. Do not expose this server to other people.")
        app.state.settings = s
        app.state.repo = repo or build_repo(s)
        app.state.db = db or Database(s.app_database_url)
        app.state.db.create_all()
        app.state.events = SecurityEvents(app.state.db)
        app.state.events.seed_thresholds()
        if s.seed_demo_data:
            with app.state.db.session() as session:
                added = seed_catalogue(session, s.store_currency)
                if s.local_auth_enabled:
                    added["demo_users"] = seed_demo_users(session)
            if any(added.values()):
                log.info("seeded demonstration data: %s", added)
        app.state.providers = providers if providers is not None else build_providers(s)
        if predictor is None:
            p = Predictor(s.risk_high, s.risk_medium, s.model_threshold)
            p.load(s.model_path)
            app.state.predictor = p
        else:
            app.state.predictor = predictor
        app.state.pca = PcaPredictor(s.risk_high, s.risk_medium, s.model_threshold)
        app.state.pca.load(s.pca_model_path)
        app.state.limiter = RateLimiter()
        pr = app.state.predictor
        log.info("model %s", "loaded " + pr.metadata["version"] if pr.available else "NOT loaded: " + pr.error)
        yield
        app.state.db.dispose()

    app = FastAPI(title="FraudGuard API", version="3.0.0", lifespan=lifespan,
                  docs_url="/docs" if s.docs_enabled else None, redoc_url=None,
                  openapi_url="/openapi.json" if s.docs_enabled else None,
                  description="Demonstration retail store and fraud/security console. Payments are simulated; "
                              "no real retailer system is connected.")
    app.add_middleware(BodyLimitMiddleware, max_bytes=s.max_body_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"], expose_headers=["X-Request-ID"])

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
                   investigations, reports, admin):
        app.include_router(module.router)
    return app
