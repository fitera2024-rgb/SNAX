from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from snax_import.domain.errors import InvalidValue
from snax_import.domain.processing import ProcessingRun as ProcessingRun
from snax_import.domain.state_machine import ImportStatus, validate_transition
from snax_import.domain.value_objects import (
    CorrelationId,
    FileSize,
    IdempotencyKey,
    MediaType,
    ObjectKey,
    OriginalFileName,
    Sha256Digest,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _validate_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise InvalidValue(field, "Timestamp должен быть timezone-aware UTC")


def _validate_nonblank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidValue(field, "Значение обязательно")


class StorageStatus(StrEnum):
    STORED = "STORED"
    ORPHANED = "ORPHANED"


@dataclass(frozen=True, slots=True)
class SourceFile:
    id: UUID
    sha256: Sha256Digest
    object_key: ObjectKey
    original_filename: OriginalFileName
    media_type: MediaType
    size: FileSize
    storage_status: StorageStatus
    created_at: datetime

    def __post_init__(self) -> None:
        _validate_utc(self.created_at, "createdAt")
        if self.object_key != ObjectKey.for_digest(self.sha256):
            raise InvalidValue("objectKey", "Object key должен соответствовать SHA-256")

    @classmethod
    def create(
        cls,
        *,
        sha256: Sha256Digest,
        object_key: ObjectKey,
        original_filename: OriginalFileName,
        media_type: MediaType,
        size: FileSize,
        now: datetime | None = None,
    ) -> SourceFile:
        return cls(
            id=uuid4(),
            sha256=sha256,
            object_key=object_key,
            original_filename=original_filename,
            media_type=media_type,
            size=size,
            storage_status=StorageStatus.STORED,
            created_at=now or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class ImportStatusEvent:
    id: UUID
    import_id: UUID
    sequence: int
    previous_status: ImportStatus | None
    new_status: ImportStatus
    occurred_at: datetime
    reason: str
    correlation_id: CorrelationId
    actor: str

    def __post_init__(self) -> None:
        _validate_utc(self.occurred_at, "occurredAt")
        if self.sequence < 1:
            raise InvalidValue("sequence", "Последовательность события должна быть положительной")
        _validate_nonblank(self.reason, "reason")
        _validate_nonblank(self.actor, "actor")
        if self.previous_status is self.new_status:
            raise InvalidValue("newStatus", "Событие не может сохранять тот же статус")


@dataclass(frozen=True, slots=True)
class TransitionResult:
    aggregate: Import
    event: ImportStatusEvent


@dataclass(frozen=True, slots=True)
class Import:
    id: UUID
    source_file_id: UUID
    status: ImportStatus
    version: int
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    created_at: datetime
    updated_at: datetime
    supplier_code: str | None = None
    profile_code: str | None = None
    event_sequence: int = 0

    def __post_init__(self) -> None:
        _validate_utc(self.created_at, "createdAt")
        _validate_utc(self.updated_at, "updatedAt")
        if self.updated_at < self.created_at:
            raise InvalidValue("updatedAt", "updatedAt не может быть раньше createdAt")
        if self.version < 1:
            raise InvalidValue("version", "Версия aggregate должна быть положительной")
        if self.event_sequence < 0:
            raise InvalidValue("eventSequence", "Номер события не может быть отрицательным")

    @classmethod
    def create(
        cls,
        *,
        source_file_id: UUID,
        correlation_id: CorrelationId,
        idempotency_key: IdempotencyKey,
        supplier_code: str | None = None,
        profile_code: str | None = None,
        now: datetime | None = None,
    ) -> Import:
        timestamp = now or utc_now()
        return cls(
            id=uuid4(),
            source_file_id=source_file_id,
            status=ImportStatus.RECEIVED,
            version=1,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            created_at=timestamp,
            updated_at=timestamp,
            supplier_code=supplier_code,
            profile_code=profile_code,
            event_sequence=1,
        )

    def initial_event(self, *, reason: str, actor: str = "system") -> ImportStatusEvent:
        return ImportStatusEvent(
            id=uuid4(),
            import_id=self.id,
            sequence=1,
            previous_status=None,
            new_status=self.status,
            occurred_at=self.created_at,
            reason=reason,
            correlation_id=self.correlation_id,
            actor=actor,
        )

    def transition(
        self,
        target: ImportStatus,
        *,
        reason: str,
        correlation_id: CorrelationId | None = None,
        actor: str = "system",
        now: datetime | None = None,
    ) -> TransitionResult:
        _validate_nonblank(reason, "reason")
        _validate_nonblank(actor, "actor")
        validate_transition(self.status, target)
        timestamp = now or utc_now()
        _validate_utc(timestamp, "occurredAt")
        if timestamp < self.updated_at:
            raise InvalidValue("occurredAt", "Событие не может предшествовать aggregate")
        event = ImportStatusEvent(
            id=uuid4(),
            import_id=self.id,
            sequence=self.event_sequence + 1,
            previous_status=self.status,
            new_status=target,
            occurred_at=timestamp,
            reason=reason,
            correlation_id=correlation_id or self.correlation_id,
            actor=actor,
        )
        aggregate = Import(
            id=self.id,
            source_file_id=self.source_file_id,
            status=target,
            version=self.version + 1,
            correlation_id=self.correlation_id,
            idempotency_key=self.idempotency_key,
            created_at=self.created_at,
            updated_at=timestamp,
            supplier_code=self.supplier_code,
            profile_code=self.profile_code,
            event_sequence=event.sequence,
        )
        return TransitionResult(aggregate=aggregate, event=event)

    def retry(self, *, reason: str, now: datetime | None = None) -> TransitionResult:
        return self.transition(ImportStatus.QUEUED, reason=reason, now=now)
