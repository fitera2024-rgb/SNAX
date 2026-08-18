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
    s3_bucket: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
