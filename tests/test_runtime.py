from __future__ import annotations

import pytest

from snax_import.config import Settings
from snax_import.runtime import build_runtime


def test_runtime_rejects_partial_database_and_storage_configuration() -> None:
    with pytest.raises(RuntimeError, match="configured together"):
        build_runtime(
            Settings(
                app_env="test",
                database_url="postgresql+psycopg://snax:snax@postgres/snax",
                _env_file=None,
            )
        )

    with pytest.raises(RuntimeError, match="configured together"):
        build_runtime(
            Settings(
                app_env="test",
                s3_endpoint="http://minio:9000",
                s3_access_key="local",
                _env_file=None,
            )
        )


def test_runtime_normalizes_blank_temp_directory_for_local_fallback() -> None:
    runtime = build_runtime(
        Settings(
            app_env="test",
            temp_directory="",
            allow_in_memory_fallback=True,
            _env_file=None,
        )
    )
    assert runtime.service.temp_directory is None
