from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from snax_import.domain.errors import InvalidTransition, TerminalStateError


class ImportStatus(StrEnum):
    RECEIVED = "RECEIVED"
    STORED = "STORED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS = MappingProxyType(
    {
        ImportStatus.RECEIVED: frozenset({ImportStatus.STORED, ImportStatus.CANCELLED}),
        ImportStatus.STORED: frozenset({ImportStatus.QUEUED, ImportStatus.CANCELLED}),
        ImportStatus.QUEUED: frozenset({ImportStatus.PROCESSING, ImportStatus.CANCELLED}),
        ImportStatus.PROCESSING: frozenset({ImportStatus.READY_FOR_REVIEW, ImportStatus.FAILED}),
        ImportStatus.READY_FOR_REVIEW: frozenset(),
        ImportStatus.FAILED: frozenset({ImportStatus.QUEUED}),
        ImportStatus.CANCELLED: frozenset(),
    }
)


def validate_transition(previous: ImportStatus, requested: ImportStatus) -> None:
    if requested in ALLOWED_TRANSITIONS[previous]:
        return
    if not ALLOWED_TRANSITIONS[previous]:
        raise TerminalStateError(previous.value, requested.value)
    raise InvalidTransition(previous.value, requested.value)
