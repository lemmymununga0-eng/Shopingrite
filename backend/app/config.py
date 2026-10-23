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
    seed_zm_catalogue: bool = True          # the Zambian catalogue (db/catalogue_zm.py)
    seed_legacy_demo: bool = False          # the original generic DEMO-* catalogue (tests turn this on)
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
    ml_artifact_dir: Path = BACKEND_DIR / "artifacts" / "fraud"
    model_threshold: float | None = Field(None, ge=0, le=1)   # overrides the threshold stored in the artifact
    risk_high: float = Field(0.7, ge=0, le=1)
    risk_medium: float = Field(0.3, ge=0, le=1)

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    docs_enabled: bool = True
    max_body_bytes: int = 20_000

    # --- Rate limits (requests per minute, in-memory, per user or per client address) ---
    predict_rate_limit_per_min: int = 30
    checkout_rate_limit_per_min: int = 10
    payment_check_rate_limit_per_min: int = 90      # the payment page checks every 5 s (12/min) while a customer pays
    cart_rate_limit_per_min: int = 120
    scamwatch_rate_limit_per_min: int = 20
    login_rate_limit_per_min: int = 10

    # --- Store identity (configurable; a retailer-authorised deployment would change these) ---
    store_name: str = "FreshCart Demo Store"
    store_currency: str = Field("ZMW", pattern=r"^[A-Z]{3}$")
    store_is_demo: bool = True
    # true = only administrators may enter the staff console; fraud/security analyst accounts are treated as customers
    console_admin_only: bool = False
    # Shown on the Contact / Terms / Privacy pages of a live store (STORE_IS_DEMO=false). Real details are required in production.
    store_legal_name: str = ""                 # the business's registered name; falls back to STORE_NAME
    store_contact_email: str = ""
    store_contact_phone: str = ""
    store_contact_address: str = ""
    delivery_fee_cents: int = Field(3500, ge=0)
    free_delivery_over_cents: int = Field(60000, ge=0)
    delivery_cities: str = "Lusaka,Kitwe,Ndola,Livingstone"
    max_quantity_per_line: int = Field(20, ge=1)
    payment_hold_minutes: int = Field(30, ge=1, le=1440)   # stock is held this long while an order awaits payment
    cod_enabled: bool = False                              # cash on delivery, only if the administrator enables it
    payments_simulated_enabled: bool = True                # the labelled demonstration payment provider
    payment_webhook_secret: str = ""                       # HMAC secret for provider callbacks; empty = webhooks off

    # --- Flutterwave (real card + Zambian mobile-money payments). Empty secret key = the method is not offered ---
    flw_secret_key: str = ""                               # FLWSECK_TEST-... (test mode) or FLWSECK-... (live). Server only.
    flw_webhook_hash: str = ""                             # "secret hash" typed into the Flutterwave dashboard webhook form
    flw_base_url: str = "https://api.flutterwave.com/v3"
    flw_timeout_seconds: float = Field(15.0, gt=0, le=60)
    frontend_url: str = "http://localhost:5173"            # where Flutterwave sends the customer back after paying

    # --- Optional customer e-mail (order confirmed / progress / cancelled / refunded). Empty host = no e-mail ---
    smtp_host: str = ""
    smtp_port: int = 587                                   # 587 = STARTTLS, 465 = implicit TLS
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""                                    # e.g. "Mwila Foods <orders@mwila.example>"
    smtp_starttls: bool = True

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
        url = self.database_url.strip()
        if not url:
            return f"sqlite:///{(BACKEND_DIR / 'data' / 'fraudguard_app.db').as_posix()}"
        # Hosts such as Render hand out "postgres://" or "postgresql://"; SQLAlchemy needs the driver named.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def flutterwave_enabled(self) -> bool:
        return bool(self.flw_secret_key.strip())

    @property
    def flutterwave_test_mode(self) -> bool:
        return self.flw_secret_key.strip().upper().startswith("FLWSECK_TEST")

    def production_problems(self) -> list[str]:
        """Settings that would make a public deployment unsafe. Empty list = fine. Checked at startup in production."""
        out = []
        if self.local_auth_enabled:
            out.append("LOCAL_AUTH_ENABLED must be false (it creates accounts with a published password).")
        if not self.supabase_url or "YOUR-PROJECT" in self.supabase_url:
            out.append("SUPABASE_URL must be set: real sign-in is required in production.")
        if self.database_url.strip() == "":
            out.append("DATABASE_URL must point at PostgreSQL (the SQLite file is lost on most hosts).")
        if self.payments_simulated_enabled:
            out.append("PAYMENTS_SIMULATED_ENABLED must be false: simulated payments would let anyone 'pay' for free.")
        if self.flw_secret_key and not self.flw_webhook_hash:
            out.append("FLW_WEBHOOK_HASH must be set when FLW_SECRET_KEY is set (webhooks cannot be authenticated otherwise).")
        if self.seed_demo_data:
            out.append("SEED_DEMO_DATA must be false: the sample catalogue has invented prices and must not be sold. "
                       "Add your real products in the Products screen.")
        if self.store_is_demo:
            out.append("STORE_IS_DEMO must be false on a live store.")
        if not self.store_contact_email.strip() or "@" not in self.store_contact_email:
            out.append("STORE_CONTACT_EMAIL must be set: customers need a real way to reach you (shown on the Contact page).")
        if self.docs_enabled:
            out.append("DOCS_ENABLED should be false.")
        if any("localhost" in o or "127.0.0.1" in o for o in self.cors_list):
            out.append("CORS_ORIGINS must list only your real frontend origin.")
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
