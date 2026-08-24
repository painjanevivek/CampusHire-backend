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
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "test"]
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
    resume_worker_lease_seconds: int = Field(default=300, ge=30, le=3_600)
    resume_parser_backend: Literal["subprocess", "docker"] = "subprocess"
    resume_parser_image: str = "campushire-pdf-parser:local"
    resume_parser_timeout_seconds: float = Field(default=20.0, ge=1, le=120)
    resume_parser_memory_megabytes: int = Field(default=256, ge=64, le=1_024)
    resume_parser_cpus: float = Field(default=0.5, ge=0.1, le=4)
    resume_parser_pids_limit: int = Field(default=32, ge=8, le=128)
    privacy_cleanup_max_attempts: int = Field(default=5, ge=1, le=20)
    privacy_cleanup_lease_seconds: int = Field(default=300, ge=30, le=3_600)
    malware_scanner: Literal["marker", "clamav"] = "marker"
    clamav_host: str = "127.0.0.1"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
    gemini_api_key: str | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_timeout_ms: int = Field(default=15_000, ge=1_000, le=120_000)
    semantic_match_requests_per_minute: int = Field(default=10, ge=1, le=100)
    qdrant_url: str = "http://localhost:6333"

    @model_validator(mode="after")
    def production_requires_real_malware_scanning(self) -> "Settings":
        if self.app_env in {"staging", "production"} and self.malware_scanner != "clamav":
            raise ValueError("Staging and production require MALWARE_SCANNER=clamav")
        if self.app_env in {"staging", "production"} and self.resume_parser_backend != "docker":
            raise ValueError("Staging and production require RESUME_PARSER_BACKEND=docker")
        if self.app_env in {"staging", "production"}:
            if any(origin.scheme != "https" for origin in self.frontend_origins):
                raise ValueError("Staging and production require HTTPS FRONTEND_ORIGINS")
            if not self.trusted_hosts or "*" in self.trusted_hosts:
                raise ValueError("Staging and production require explicit TRUSTED_HOSTS")
        return self

    @property
    def is_development(self) -> bool:
        return self.app_env in {"development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
