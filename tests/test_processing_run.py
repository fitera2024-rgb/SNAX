from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from snax_import.domain.errors import JobAlreadyClaimed, JobLeaseLost, JobNotClaimable
from snax_import.domain.processing import ProcessingRun, ProcessingRunStatus

NOW = datetime(2026, 8, 18, tzinfo=UTC)
TOKEN = UUID("10000000-0000-4000-8000-000000000001")


def test_processing_run_claim_heartbeat_and_success() -> None:
    queued = ProcessingRun.create(uuid4(), 1, correlation_id="corr", now=NOW)
    claimed = queued.claim(
        worker_id="worker-1",
        lease_token=TOKEN,
        lease_duration=timedelta(seconds=30),
        now=NOW,
    )
    assert claimed.status is ProcessingRunStatus.PROCESSING
    assert claimed.delivery_count == 1
    with pytest.raises(JobAlreadyClaimed):
        claimed.claim(
            worker_id="worker-2",
            lease_token=uuid4(),
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
    heartbeat = claimed.heartbeat(
        worker_id="worker-1",
        lease_token=TOKEN,
        lease_duration=timedelta(seconds=30),
        now=NOW + timedelta(seconds=10),
    )
    assert heartbeat.lease_expires_at == NOW + timedelta(seconds=40)
    succeeded = heartbeat.succeed(
        worker_id="worker-1", lease_token=TOKEN, now=NOW + timedelta(seconds=20)
    )
    assert succeeded.status is ProcessingRunStatus.SUCCEEDED
    assert succeeded.lease_token is None
    with pytest.raises(JobNotClaimable):
        queued.heartbeat(
            worker_id="worker-1",
            lease_token=TOKEN,
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )


def test_processing_run_rejects_stale_lease_and_times_out() -> None:
    queued = ProcessingRun.create(uuid4(), 1, correlation_id="corr", now=NOW)
    claimed = queued.claim(
        worker_id="worker-1",
        lease_token=TOKEN,
        lease_duration=timedelta(seconds=30),
        now=NOW,
    )
    with pytest.raises(JobLeaseLost):
        claimed.succeed(worker_id="worker-2", lease_token=TOKEN, now=NOW + timedelta(seconds=1))
    timed_out = claimed.timeout(
        code="JOB_HEARTBEAT_EXPIRED",
        reason="lease expired",
        now=NOW + timedelta(seconds=31),
    )
    assert timed_out.status is ProcessingRunStatus.TIMED_OUT
    dead = timed_out.dead_letter(
        code="RETRY_BUDGET_EXHAUSTED",
        reason="no attempts left",
        retryable=True,
        now=NOW + timedelta(seconds=32),
    )
    assert dead.status is ProcessingRunStatus.DEAD_LETTERED
