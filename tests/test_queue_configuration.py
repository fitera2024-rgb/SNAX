from __future__ import annotations

import pytest
from pydantic import ValidationError

from snax_import.config import Settings


@pytest.mark.parametrize(
    "values",
    [
        {"job_heartbeat_seconds": 30, "job_lease_seconds": 30},
        {"worker_soft_time_limit_seconds": 900, "worker_hard_time_limit_seconds": 900},
        {"worker_hard_time_limit_seconds": 900, "queue_visibility_timeout_seconds": 900},
        {"queue_message_max_bytes": 0},
    ],
)
def test_invalid_queue_timing_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(**values)


def test_test_processor_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", processor_mode="source-integrity-test")


def test_autostart_requires_broker() -> None:
    with pytest.raises(ValidationError):
        Settings(processing_autostart=True, queue_broker_url=None, redis_url=None)
