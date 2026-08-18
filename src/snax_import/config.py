from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "SNAX"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    public_version_contract: str = "1.1.0"
    commit_sha: str = "unknown"
    onec_base_url: str = ""

    database_url: str | None = None
    redis_url: str | None = None
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_force_path_style: bool = True
    max_upload_bytes: int = 100 * 1024 * 1024
    temp_directory: str | None = None
    verify_object_digest: bool = True
    allow_in_memory_fallback: bool = True

    queue_broker_url: str | None = None
    queue_name: str = "snax.import.processing.v1"
    queue_visibility_timeout_seconds: int = 3600

    outbox_batch_size: int = 50
    outbox_poll_interval_seconds: float = 1.0
    outbox_lock_seconds: int = 30
    outbox_max_publish_attempts: int = 10
    outbox_retry_base_seconds: float = 1.0
    outbox_retry_max_seconds: float = 60.0

    worker_id: str = "snax-worker-local"
    worker_concurrency: int = 1
    worker_prefetch_multiplier: int = 1
    worker_soft_time_limit_seconds: int = 840
    worker_hard_time_limit_seconds: int = 900

    job_lease_seconds: int = 45
    job_heartbeat_seconds: int = 10

    processing_max_attempts: int = 3
    processing_retry_base_seconds: float = 5.0
    processing_retry_max_seconds: float = 300.0
    processing_retry_multiplier: float = 2.0
    processing_retry_jitter_ratio: float = 0.2
    processing_autostart: bool = False
    processor_mode: str = "disabled"

    recovery_poll_interval_seconds: float = 5.0
    queue_redelivery_after_seconds: int = 120

    @model_validator(mode="after")
    def validate_queue_settings(self) -> Settings:
        positive = {
            "queue_visibility_timeout_seconds": self.queue_visibility_timeout_seconds,
            "outbox_batch_size": self.outbox_batch_size,
            "outbox_poll_interval_seconds": self.outbox_poll_interval_seconds,
            "outbox_lock_seconds": self.outbox_lock_seconds,
            "outbox_max_publish_attempts": self.outbox_max_publish_attempts,
            "outbox_retry_base_seconds": self.outbox_retry_base_seconds,
            "outbox_retry_max_seconds": self.outbox_retry_max_seconds,
            "worker_concurrency": self.worker_concurrency,
            "worker_prefetch_multiplier": self.worker_prefetch_multiplier,
            "worker_soft_time_limit_seconds": self.worker_soft_time_limit_seconds,
            "worker_hard_time_limit_seconds": self.worker_hard_time_limit_seconds,
            "job_lease_seconds": self.job_lease_seconds,
            "job_heartbeat_seconds": self.job_heartbeat_seconds,
            "processing_max_attempts": self.processing_max_attempts,
            "processing_retry_base_seconds": self.processing_retry_base_seconds,
            "processing_retry_max_seconds": self.processing_retry_max_seconds,
            "processing_retry_multiplier": self.processing_retry_multiplier,
            "recovery_poll_interval_seconds": self.recovery_poll_interval_seconds,
            "queue_redelivery_after_seconds": self.queue_redelivery_after_seconds,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise ValueError(f"Queue settings must be positive: {', '.join(invalid)}")
        if self.job_heartbeat_seconds >= self.job_lease_seconds:
            raise ValueError("JOB_HEARTBEAT_SECONDS must be less than JOB_LEASE_SECONDS")
        if self.job_lease_seconds < self.job_heartbeat_seconds * 3:
            raise ValueError("JOB_LEASE_SECONDS must be at least 3x JOB_HEARTBEAT_SECONDS")
        if self.worker_soft_time_limit_seconds >= self.worker_hard_time_limit_seconds:
            raise ValueError("WORKER_SOFT_TIME_LIMIT_SECONDS must be less than hard limit")
        if self.worker_hard_time_limit_seconds >= self.queue_visibility_timeout_seconds:
            raise ValueError("Worker hard limit must be less than queue visibility timeout")
        if not 0 <= self.processing_retry_jitter_ratio <= 1:
            raise ValueError("PROCESSING_RETRY_JITTER_RATIO must be between 0 and 1")
        if self.processor_mode not in {"disabled", "source-integrity-test"}:
            raise ValueError("Unknown PROCESSOR_MODE")
        production_like = self.app_env.lower() in {"production", "prod", "staging"}
        if production_like and self.processor_mode == "source-integrity-test":
            raise ValueError("Test processor is forbidden in production-like environments")
        if production_like and self.processing_autostart:
            raise ValueError("Production-like autostart requires a configured real processor")
        if self.processing_autostart and not (self.queue_broker_url or self.redis_url):
            raise ValueError("PROCESSING_AUTOSTART requires QUEUE_BROKER_URL")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
