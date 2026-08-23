from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+asyncpg://campushire:campushire@localhost:5432/campushire"
    redis_url: str = "redis://localhost:6379/0"
    frontend_origins: list[AnyHttpUrl] = Field(
        default_factory=lambda: [AnyHttpUrl("http://localhost:3000")]
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    session_cookie_name: str = "campushire_session"
    csrf_cookie_name: str = "campushire_csrf"
    session_ttl_hours: int = Field(default=12, ge=1, le=720)
    resume_storage_path: str = ".data/resumes"
    resume_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    resume_max_pages: int = Field(default=3, ge=1, le=20)
    resume_max_versions: int = Field(default=25, ge=1, le=100)
    resume_job_max_attempts: int = Field(default=3, ge=1, le=10)
    resume_worker_poll_seconds: float = Field(default=2.0, ge=0.2, le=30)
    malware_scanner: Literal["marker", "clamav"] = "marker"
    clamav_host: str = "127.0.0.1"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
    gemini_api_key: str | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    qdrant_url: str = "http://localhost:6333"

    @model_validator(mode="after")
    def production_requires_real_malware_scanning(self) -> "Settings":
        if self.app_env in {"staging", "production"} and self.malware_scanner != "clamav":
            raise ValueError("Staging and production require MALWARE_SCANNER=clamav")
        return self

    @property
    def is_development(self) -> bool:
        return self.app_env in {"development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
