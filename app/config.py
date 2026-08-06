from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/textileops"
    gemini_api_key: str = ""
    gcs_bucket: str = ""
    bq_dataset: str = "textile_ops"

    # Where uploaded media lands until gcs_bucket is configured. Local disk is
    # fine for the launch cohort; on Cloud Run it is per-instance and ephemeral.
    upload_dir: str = "var/uploads"

    # Gates tenant creation. Required outside dev — without it, anyone who can
    # reach the service can mint a tenant and its token.
    admin_token: str = ""

    auto_commit_floor: float = 0.85
    default_overdue_days: int = 45
    env: str = "dev"

    # Close-of-business digest. Delivery is stdlib SMTP; if smtp_host is empty
    # the digest is still composed and stored, just not sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_ssl: bool = False
    smtp_starttls: bool = True
    digest_from: str = ""
    dashboard_url: str = "http://localhost:3000"

    # Cloud Scheduler hits the digest endpoint with this; it is not a tenant
    # token because the run is cross-tenant.
    scheduler_token: str = ""

    class Config:
        env_file = ".env"


@lru_cache
def settings() -> Settings:
    return Settings()
