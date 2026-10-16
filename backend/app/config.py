"""Environment-based settings. Values come from backend/.env or real environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # "sqlite" = local development/tests, "supabase" = Supabase Postgres via PostgREST + RLS.
    db_backend: str = "sqlite"
    sqlite_path: Path = BACKEND_DIR / "data" / "fraudguard.db"

    supabase_url: str = ""
    supabase_anon_key: str = ""          # public anon key only. The service-role key is never used.
    supabase_jwt_secret: str = ""        # HS256 projects. Leave empty to use the JWKS endpoint instead.
    jwt_audience: str = "authenticated"

    model_path: Path = BACKEND_DIR / "models" / "fraud_model.joblib"
    pca_model_path: Path = BACKEND_DIR / "models" / "pca_demo_model.joblib"
    risk_high: float = Field(0.7, ge=0, le=1)
    risk_medium: float = Field(0.3, ge=0, le=1)

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    predict_rate_limit_per_min: int = 30
    max_body_bytes: int = 20_000

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
