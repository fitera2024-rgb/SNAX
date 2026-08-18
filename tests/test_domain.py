from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from uuid import uuid4

import pytest

from snax_import.domain.entities import Import, ImportStatusEvent, ProcessingRun, SourceFile
from snax_import.domain.errors import InvalidTransition, InvalidValue, TerminalStateError
from snax_import.domain.state_machine import ALLOWED_TRANSITIONS, ImportStatus
from snax_import.domain.value_objects import (
    CorrelationId,
    FileSize,
    IdempotencyKey,
    MediaType,
    ObjectKey,
    OriginalFileName,
    Sha256Digest,
)


def test_value_objects_validate_digest_size_and_metadata() -> None:
    digest = Sha256Digest("a" * 64)
    assert ObjectKey.for_digest(digest).value == f"raw/sha256/aa/aa/{'a' * 64}"
    assert FileSize(0).value == 0
    assert MediaType(" Application/PDF ").value == "application/pdf"
    assert OriginalFileName("price-list.pdf").value == "price-list.pdf"
    assert IdempotencyKey("idempotency-key-001").value == "idempotency-key-001"
    assert CorrelationId("corr-001").value == "corr-001"

    with pytest.raises(InvalidValue):
        Sha256Digest("A" * 64)
    with pytest.raises(InvalidValue):
        Sha256Digest("not-a-digest")
    with pytest.raises(InvalidValue):
        FileSize(-1)
    with pytest.raises(InvalidValue):
        OriginalFileName("..\\secret.xlsx")
    with pytest.raises(InvalidValue):
        OriginalFileName("bad\x00name.xlsx")


def test_entities_reject_naive_timestamps_and_invalid_versions() -> None:
    with pytest.raises(InvalidValue):
        Import(
            id=uuid4(),
            source_file_id=uuid4(),
            status=ImportStatus.RECEIVED,
            version=1,
            correlation_id=CorrelationId("correlation-001"),
            idempotency_key=IdempotencyKey("idempotency-0001"),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    now = datetime.now(UTC)
    with pytest.raises(InvalidValue):
        Import(
            id=uuid4(),
            source_file_id=uuid4(),
            status=ImportStatus.RECEIVED,
            version=0,
            correlation_id=CorrelationId("correlation-001"),
            idempotency_key=IdempotencyKey("idempotency-0001"),
            created_at=now,
            updated_at=now,
        )
    with pytest.raises(InvalidValue):
        Import(
            id=uuid4(),
            source_file_id=uuid4(),
            status=ImportStatus.RECEIVED,
            version=1,
            correlation_id=CorrelationId("correlation-001"),
            idempotency_key=IdempotencyKey("idempotency-0001"),
            created_at=now,
            updated_at=now - timedelta(seconds=1),
        )


def test_source_file_requires_object_key_for_its_digest() -> None:
    now = datetime.now(UTC)
    digest = Sha256Digest("a" * 64)
    other_digest = Sha256Digest("b" * 64)
    with pytest.raises(InvalidValue):
        SourceFile.create(
            sha256=digest,
            object_key=ObjectKey.for_digest(other_digest),
            original_filename=OriginalFileName("price.xlsx"),
            media_type=MediaType("application/octet-stream"),
            size=FileSize(10),
            now=now,
        )


def test_events_and_processing_runs_enforce_domain_invariants() -> None:
    now = datetime.now(UTC)
    with pytest.raises(InvalidValue):
        ImportStatusEvent(
            id=uuid4(),
            import_id=uuid4(),
            sequence=0,
            previous_status=None,
            new_status=ImportStatus.RECEIVED,
            occurred_at=now,
            reason="created",
            correlation_id=CorrelationId("correlation-001"),
            actor="system",
        )
    with pytest.raises(InvalidValue):
        ImportStatusEvent(
            id=uuid4(),
            import_id=uuid4(),
            sequence=2,
            previous_status=ImportStatus.STORED,
            new_status=ImportStatus.STORED,
            occurred_at=now,
            reason="same status",
            correlation_id=CorrelationId("correlation-001"),
            actor="system",
        )
    with pytest.raises(InvalidValue):
        ProcessingRun.create(uuid4(), 0)
    with pytest.raises(InvalidValue):
        replace(
            ProcessingRun.create(uuid4(), 1, now=now),
            started_at=now,
            completed_at=now - timedelta(seconds=1),
        )


def _aggregate() -> Import:
    return Import.create(
        source_file_id=uuid4(),
        correlation_id=CorrelationId("correlation-001"),
        idempotency_key=IdempotencyKey("idempotency-0001"),
    )


def test_every_transition_is_typed_and_terminal_states_are_protected() -> None:
    received = _aggregate()
    statuses = {
        ImportStatus.RECEIVED: received,
        ImportStatus.STORED: received.transition(ImportStatus.STORED, reason="setup").aggregate,
    }
    statuses[ImportStatus.QUEUED] = (
        statuses[ImportStatus.STORED].transition(ImportStatus.QUEUED, reason="setup").aggregate
    )
    statuses[ImportStatus.PROCESSING] = (
        statuses[ImportStatus.QUEUED].transition(ImportStatus.PROCESSING, reason="setup").aggregate
    )
    statuses[ImportStatus.READY_FOR_REVIEW] = (
        statuses[ImportStatus.PROCESSING]
        .transition(ImportStatus.READY_FOR_REVIEW, reason="setup")
        .aggregate
    )
    failed = (
        statuses[ImportStatus.PROCESSING].transition(ImportStatus.FAILED, reason="setup").aggregate
    )
    statuses[ImportStatus.FAILED] = failed
    statuses[ImportStatus.CANCELLED] = received.transition(
        ImportStatus.CANCELLED, reason="setup"
    ).aggregate
    for previous, requested in product(ImportStatus, ImportStatus):
        aggregate = statuses[previous]
        allowed = requested in ALLOWED_TRANSITIONS[previous]
        if allowed:
            assert aggregate.transition(requested, reason="test").aggregate.status is requested
        else:
            error_type = (
                TerminalStateError if not ALLOWED_TRANSITIONS[previous] else InvalidTransition
            )
            with pytest.raises(error_type):
                aggregate.transition(requested, reason="test")


def test_retry_is_explicit_and_events_are_append_only_ordered() -> None:
    aggregate = _aggregate()
    received = aggregate.initial_event(reason="created")
    failed = aggregate.transition(ImportStatus.STORED, reason="stored").aggregate
    failed = failed.transition(ImportStatus.QUEUED, reason="queued").aggregate
    failed = failed.transition(ImportStatus.PROCESSING, reason="processing").aggregate
    failed = failed.transition(ImportStatus.FAILED, reason="failed").aggregate
    retry = failed.retry(reason="operator retry")
    assert received.sequence == 1
    assert retry.event.sequence == 6
    assert retry.aggregate.status is ImportStatus.QUEUED
    assert retry.aggregate.version == failed.version + 1
    assert failed.status is ImportStatus.FAILED
