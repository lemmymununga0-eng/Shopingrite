"""Application factory: builds the FastAPI app so tests can create isolated instances."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .db.sqlite_repo import SqliteRepository
from .db.supabase_repo import SupabaseRepository
from .dependencies import RateLimiter
from .ml.pca_demo import PcaPredictor
from .ml.predict import Predictor
from .routers import pca_demo as pca_router, system, transactions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)   # do not log request URLs
log = logging.getLogger("fraudguard")


def build_repo(s: Settings):
    if s.db_backend == "supabase":
        return SupabaseRepository(s.supabase_url, s.supabase_anon_key)
    if s.db_backend == "sqlite":
        return SqliteRepository(s.sqlite_path)
    raise RuntimeError(f"Unknown DB_BACKEND '{s.db_backend}' (use 'sqlite' or 'supabase')")


def create_app(settings: Settings | None = None, repo=None, predictor: Predictor | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = s
        app.state.repo = repo or build_repo(s)
        if predictor is None:
            p = Predictor(s.risk_high, s.risk_medium)
            p.load(s.model_path)
            app.state.predictor = p
        else:
            app.state.predictor = predictor
        app.state.pca = PcaPredictor()
        app.state.pca.load(s.pca_model_path)
        app.state.limiter = RateLimiter()
        pr = app.state.predictor
        log.info("model %s", "loaded " + pr.metadata["version"] if pr.available else "NOT loaded: " + pr.error)
        yield

    app = FastAPI(title="Shoprite FraudGuard API", version="2.0.0", lifespan=lifespan,
                  description="Educational fraud-detection MVP. Does not process real payments.")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > s.max_body_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Report where and why, but never echo the submitted values (they may be NaN or sensitive).
        errors = [{"field": ".".join(str(x) for x in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]}
                  for e in exc.errors()]
        return JSONResponse({"detail": "Validation failed", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.include_router(system.router)
    app.include_router(transactions.router)
    app.include_router(pca_router.router)
    return app
