from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CPM_", env_file=".env", extra="ignore")

    # --- core ---
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = f"sqlite:///{(DATA_DIR / 'cpm.db').as_posix()}"

    # --- managed Postgres, e.g. RDS (used instead of database_url when db_host is set) ---
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "cpm"
    db_user: str | None = None
    db_password: str | None = None

    # --- auth (PRD 8, 73) ---
    jwt_secret: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_ttl_min: int = 30
    refresh_ttl_days: int = 14
    otp_ttl_min: int = 5
    expose_otp: bool = True  # dev convenience: return the OTP in the login response

    # --- evidence storage (PRD 48, 60, 74) ---
    storage_backend: str = "local"  # "local" | "s3"
    storage_dir: str = (DATA_DIR / "objects").as_posix()
    s3_bucket: str = ""
    aws_region: str = "ap-south-1"
    s3_endpoint_url: str | None = None  # set for S3-compatible providers (Supabase, R2, MinIO, ...)
    # Explicit credentials for those providers (there's no instance-role equivalent off AWS).
    # Left unset on real AWS, where boto3's default chain (EC2 instance role) is used instead.
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    signed_url_ttl_sec: int = 600
    max_upload_mb: int = 25

    # --- field defaults, all configurable (PRD 116) ---
    default_geofence_m: int = 50
    default_max_photos: int = 5
    default_min_photos_cctv: int = 1

    # --- ops ---
    cors_origins: str = "*"
    seed_on_start: bool = True

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_database_url(self) -> str:
        """Build a Postgres URL from split RDS-style settings when db_host is set,
        otherwise fall back to database_url (sqlite for local dev)."""
        if self.db_host:
            from urllib.parse import quote_plus
            user = quote_plus(self.db_user or "")
            pwd = quote_plus(self.db_password or "")
            return f"postgresql+psycopg://{user}:{pwd}@{self.db_host}:{self.db_port}/{self.db_name}"
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Path(s.storage_dir).mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
