from __future__ import annotations

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
