"""Application settings, read from environment variables (or a local .env file)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CERTGEN_", extra="ignore")

    # Any SQLAlchemy URL works; SQLite keeps local setup to zero dependencies.
    database_url: str = "sqlite:///./certificates.db"

    # Where generated PDF files are written.
    storage_dir: Path = Path("./storage")

    # "background" runs jobs on a worker thread pool after the request returns.
    # "sync" processes the job inside the request (used by the test suite).
    processing_mode: str = "background"

    # Number of jobs that can be processed at the same time.
    worker_threads: int = 2

    # Upper bound on recipients per request, to protect the server.
    max_recipients_per_job: int = 5000


@lru_cache
def get_settings() -> Settings:
    return Settings()
