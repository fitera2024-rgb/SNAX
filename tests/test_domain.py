from __future__ import annotations

from itertools import product
from uuid import uuid4

import pytest

from snax_import.domain.entities import Import
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
