from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/textileops"
    gemini_api_key: str = ""
    gcs_bucket: str = ""
    bq_dataset: str = "textile_ops"

    auto_commit_floor: float = 0.85
    default_overdue_days: int = 45
    env: str = "dev"

    class Config:
        env_file = ".env"


@lru_cache
def settings() -> Settings:
    return Settings()
