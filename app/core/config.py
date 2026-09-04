from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    process_role: Literal["all", "api", "worker"] = "all"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+asyncpg://campushire:campushire@localhost:5432/campushire"
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    database_pool_recycle_seconds: int = Field(default=300, ge=30, le=3_600)
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = Field(default=64, ge=1, le=1_024)
    redis_pool_timeout_seconds: float = Field(default=1.0, ge=0.1, le=10.0)
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
    invitation_ttl_hours: int = Field(default=72, ge=1, le=720)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    auth_lockout_attempts: int = Field(default=5, ge=3, le=20)
    auth_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    mfa_max_attempts: int = Field(default=5, ge=3, le=20)
    mfa_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    request_body_overhead_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    roster_max_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    operator_bootstrap_key: str | None = None
    mfa_encryption_key: str = "development-only-change-me"
    demo_login_enabled: bool = False
    demo_admin_mfa_bypass: bool = False
    demo_student_email: EmailStr | None = None
    demo_student_password: SecretStr | None = None
    demo_admin_email: EmailStr | None = None
    demo_admin_password: SecretStr | None = None
    resume_storage_path: str = ".data/resumes"
    resume_storage_backend: Literal["local", "oci"] = "local"
    oci_auth_mode: Literal["instance_principal", "api_key"] = "instance_principal"
    oci_object_namespace: str | None = None
    oci_object_bucket: str | None = None
    oci_object_uploads_enabled: bool = True
    oci_tenancy_ocid: str | None = None
    oci_user_ocid: str | None = None
    oci_key_fingerprint: str | None = None
    oci_region: str | None = None
    oci_private_key: SecretStr | None = None
    oci_private_key_passphrase: SecretStr | None = None
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
    email_smtp_host: str | None = None
    email_smtp_port: int = Field(default=587, ge=1, le=65535)
    email_smtp_username: str | None = None
    email_smtp_password: str | None = None
    email_from_address: str = "no-reply@campushire.invalid"
    email_monthly_quota: int = Field(default=3_000, ge=1)
    email_optional_suppression_ratio: float = Field(default=0.8, ge=0.1, le=1)
    email_delivery_max_attempts: int = Field(default=5, ge=1, le=20)
    email_deadline_reminder_hours: int = Field(default=24, ge=1, le=168)
    email_reminder_sweep_seconds: int = Field(default=900, ge=60, le=86_400)
    email_reminder_batch_size: int = Field(default=500, ge=1, le=5_000)
    email_delivery_webhook_key: str | None = None
    maintenance_message: str | None = None
    application_wizard_v1: bool = False
    application_packet_cleanup_seconds: int = Field(default=3600, ge=60, le=86_400)

    @model_validator(mode="after")
    def production_requires_real_malware_scanning(self) -> "Settings":
        if self.demo_login_enabled:
            if self.app_env not in {"development", "test"}:
                raise ValueError("Demo login is restricted to development and test environments")
            credentials = (
                self.demo_student_email,
                self.demo_student_password,
                self.demo_admin_email,
                self.demo_admin_password,
            )
            if any(value is None for value in credentials):
                raise ValueError(
                    "Demo login requires configured student and administrator credentials"
                )
            passwords = (self.demo_student_password, self.demo_admin_password)
            if any(
                password is not None and len(password.get_secret_value()) < 12
                for password in passwords
            ):
                raise ValueError("Demo account passwords must contain at least 12 characters")
        if self.demo_admin_mfa_bypass and not self.demo_login_enabled:
            raise ValueError("Demo administrator MFA bypass requires DEMO_LOGIN_ENABLED=true")
        if self.demo_admin_mfa_bypass and self.app_env not in {"development", "test"}:
            raise ValueError(
                "Demo administrator MFA bypass is restricted to development and test environments"
            )
        worker_enabled = self.process_role in {"all", "worker"}
        if (
            self.app_env in {"staging", "production"}
            and worker_enabled
            and self.malware_scanner != "clamav"
        ):
            raise ValueError("Staging and production require MALWARE_SCANNER=clamav")
        if (
            self.app_env in {"staging", "production"}
            and worker_enabled
            and self.resume_parser_backend != "docker"
        ):
            raise ValueError("Staging and production require RESUME_PARSER_BACKEND=docker")
        if self.app_env in {"staging", "production"}:
            if any(origin.scheme != "https" for origin in self.frontend_origins):
                raise ValueError("Staging and production require HTTPS FRONTEND_ORIGINS")
            if not self.trusted_hosts or "*" in self.trusted_hosts:
                raise ValueError("Staging and production require explicit TRUSTED_HOSTS")
            if not self.operator_bootstrap_key or len(self.operator_bootstrap_key) < 24:
                raise ValueError("Staging and production require a strong OPERATOR_BOOTSTRAP_KEY")
            if self.mfa_encryption_key == "development-only-change-me":
                raise ValueError("Staging and production require a dedicated MFA_ENCRYPTION_KEY")
            if self.email_smtp_host and (
                not self.email_delivery_webhook_key or len(self.email_delivery_webhook_key) < 24
            ):
                raise ValueError("Configured production email requires a strong webhook key")
            if self.resume_storage_backend != "oci":
                raise ValueError("Production requires private OCI Object Storage")
            if not self.oci_object_namespace or not self.oci_object_bucket:
                raise ValueError("Production requires OCI object namespace and bucket")
            if self.oci_auth_mode == "api_key":
                api_key_identity = (
                    self.oci_tenancy_ocid,
                    self.oci_user_ocid,
                    self.oci_key_fingerprint,
                    self.oci_region,
                )
                private_key = (
                    self.oci_private_key.get_secret_value()
                    if self.oci_private_key is not None
                    else ""
                )
                if any(not value or not value.strip() for value in api_key_identity) or not (
                    private_key.strip()
                ):
                    raise ValueError(
                        "OCI API key authentication requires tenancy, user, fingerprint, "
                        "region, and private key"
                    )
        return self

    @property
    def is_development(self) -> bool:
        return self.app_env in {"development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
