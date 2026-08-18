from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from snax_import.domain.errors import OutboxLeaseLost, OutboxMessageNotClaimable
from snax_import.domain.outbox import OutboxMessage, OutboxStatus

NOW = datetime(2026, 8, 18, tzinfo=UTC)


def _message() -> OutboxMessage:
    run_id = uuid4()
    return OutboxMessage.create(
        event_type="IMPORT_PROCESSING_REQUESTED",
        topic="snax.import.processing.v1",
        aggregate_type="Import",
        aggregate_id=uuid4(),
        processing_run_id=run_id,
        correlation_id="corr",
        deduplication_key=f"process:{run_id}:1",
        payload={"schemaVersion": 1},
        now=NOW,
    )


def test_outbox_claim_publish_and_lease_guard() -> None:
    pending = _message()
    claimed = pending.claim(owner="dispatcher-a", now=NOW, lock_seconds=30)
    assert claimed.status is OutboxStatus.PUBLISHING
    assert claimed.publish_attempts == 1
    with pytest.raises(OutboxLeaseLost):
        claimed.mark_published(owner="dispatcher-b", now=NOW)
    published = claimed.mark_published(owner="dispatcher-a", now=NOW + timedelta(seconds=1))
    assert published.status is OutboxStatus.PUBLISHED
    with pytest.raises(OutboxMessageNotClaimable):
        published.claim(owner="dispatcher-a", now=NOW, lock_seconds=30)


def test_outbox_failure_and_expired_lock_recovery() -> None:
    claimed = _message().claim(owner="dispatcher-a", now=NOW, lock_seconds=30)
    released = claimed.release(
        owner="dispatcher-a",
        code="BROKER_UNAVAILABLE",
        message="retry",
        available_at=NOW + timedelta(seconds=5),
        now=NOW + timedelta(seconds=1),
    )
    assert released.status is OutboxStatus.PENDING
    with pytest.raises(OutboxMessageNotClaimable):
        released.claim(owner="dispatcher-a", now=NOW + timedelta(seconds=2), lock_seconds=30)
    reclaimed = released.claim(
        owner="dispatcher-a", now=NOW + timedelta(seconds=5), lock_seconds=30
    )
    recovered = reclaimed.recover_expired(now=NOW + timedelta(seconds=36))
    assert recovered.status is OutboxStatus.PENDING
