"""Environment-based settings. Values come from backend/.env or real environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    environment: str = "development"        # "production" refuses to start with local demo auth enabled

    # --- Legacy fraud-prediction table: "sqlite" (local) or "supabase" (PostgREST + RLS) ---
    db_backend: str = "sqlite"
    sqlite_path: Path = BACKEND_DIR / "data" / "fraudguard.db"

    # --- Application database (store, cases, ScamWatch, security events, audit) ---
    # SQLite file by default; a PostgreSQL URL (postgresql+psycopg://...) works if the driver is installed.
    database_url: str = ""
    seed_demo_data: bool = True             # idempotent: only inserts missing demonstration rows

    supabase_url: str = ""
    supabase_anon_key: str = ""          # public anon key only. The service-role key is never used.
    supabase_jwt_secret: str = ""        # HS256 projects. Leave empty to use the JWKS endpoint instead.
    jwt_audience: str = "authenticated"

    # --- Local demonstration sign-in (NOT for production; off by default) ---
    local_auth_enabled: bool = False
    local_auth_secret: str = ""             # empty -> a random secret is generated into data/local_auth_secret.txt
    local_auth_token_minutes: int = 120

    model_path: Path = BACKEND_DIR / "models" / "fraud_model.joblib"
    pca_model_path: Path = BACKEND_DIR / "models" / "pca_demo_model.joblib"
    model_threshold: float | None = Field(None, ge=0, le=1)   # overrides the threshold stored in the artifact
    risk_high: float = Field(0.7, ge=0, le=1)
    risk_medium: float = Field(0.3, ge=0, le=1)

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    docs_enabled: bool = True
    max_body_bytes: int = 20_000

    # --- Rate limits (requests per minute, in-memory, per user or per client address) ---
    predict_rate_limit_per_min: int = 30
    checkout_rate_limit_per_min: int = 10
    cart_rate_limit_per_min: int = 120
    scamwatch_rate_limit_per_min: int = 20
    login_rate_limit_per_min: int = 10

    # --- Store identity (configurable; a retailer-authorised deployment would change these) ---
    store_name: str = "FreshCart Demo Store"
    store_currency: str = Field("ZAR", pattern=r"^[A-Z]{3}$")
    store_is_demo: bool = True
    delivery_fee_cents: int = Field(3500, ge=0)
    free_delivery_over_cents: int = Field(60000, ge=0)
    delivery_cities: str = "Johannesburg,Pretoria,Cape Town,Durban"
    max_quantity_per_line: int = Field(20, ge=1)

    # --- Order-risk rules (plain rules, not machine learning; see services/order_risk.py) ---
    order_high_value_cents: int = Field(500_000, ge=1)
    order_bulk_quantity: int = Field(15, ge=1)
    order_velocity_per_hour: int = Field(4, ge=1)
    order_rejection_burst: int = Field(5, ge=1)

    # --- ScamWatch providers (comma-separated names). "heuristic" is offline; "safebrowsing" needs a key ---
    scamwatch_providers: str = "heuristic"
    safe_browsing_api_key: str = ""
    # Test/demo only ("mock" provider): "bad.example=malicious,iffy.example=suspicious". Ignored in production.
    scamwatch_mock_verdicts: str = ""
    # Brand names whose look-alike domains the offline heuristic should flag, and the domains that are genuine.
    scamwatch_protected_brands: str = "shoprite"
    scamwatch_official_domains: str = "shoprite.co.za,shoprite.co.zm"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def city_list(self) -> list[str]:
        return [c.strip() for c in self.delivery_cities.split(",") if c.strip()]

    @property
    def brand_list(self) -> list[str]:
        return [b.strip().lower() for b in self.scamwatch_protected_brands.split(",") if b.strip()]

    @property
    def official_domain_list(self) -> list[str]:
        return [d.strip().lower() for d in self.scamwatch_official_domains.split(",") if d.strip()]

    @property
    def provider_list(self) -> list[str]:
        return [p.strip().lower() for p in self.scamwatch_providers.split(",") if p.strip()]

    @property
    def app_database_url(self) -> str:
        return self.database_url or f"sqlite:///{(BACKEND_DIR / 'data' / 'fraudguard_app.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
