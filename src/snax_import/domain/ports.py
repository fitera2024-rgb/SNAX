from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import BinaryIO, Protocol
from uuid import UUID

from snax_import.domain.entities import Import, ImportStatusEvent, SourceFile
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.outbox import OutboxMessage
from snax_import.domain.processing import ProcessingRun
from snax_import.domain.value_objects import ObjectKey, Sha256Digest


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: ObjectKey
    created_by_attempt: bool
    size: int
    metadata: dict[str, str]


class ObjectStoragePort(Protocol):
    def put_stream(
        self,
        stream: BinaryIO,
        *,
        object_key: ObjectKey,
        digest: Sha256Digest,
        size: int,
        media_type: str,
        metadata: dict[str, str],
    ) -> StoredObject: ...

    def get_stream(self, object_key: ObjectKey) -> AbstractContextManager[BinaryIO]: ...

    def exists(self, object_key: ObjectKey) -> bool: ...

    def verify_digest(self, object_key: ObjectKey, expected: Sha256Digest) -> None: ...

    def metadata(self, object_key: ObjectKey) -> dict[str, str]: ...

    def delete(self, object_key: ObjectKey) -> None: ...


class ImportRepositoryPort(Protocol):
    def by_id(self, import_id: UUID, *, for_update: bool = False) -> Import | None: ...

    def by_idempotency(self, key: str) -> Import | None: ...

    def by_digest(self, digest: Sha256Digest) -> Import | None: ...

    def source_for_import(self, import_id: UUID) -> SourceFile | None: ...

    def claim_stored_batch(self, *, limit: int) -> Sequence[Import]: ...

    def save_registration(
        self, source_file: SourceFile, aggregate: Import, events: Sequence[ImportStatusEvent]
    ) -> None: ...

    def save_transition(
        self, aggregate: Import, event: ImportStatusEvent, expected_version: int
    ) -> None: ...


class ProcessingRunRepositoryPort(Protocol):
    def by_id(self, run_id: UUID, *, for_update: bool = False) -> ProcessingRun | None: ...

    def active_for_import(
        self, import_id: UUID, *, for_update: bool = False
    ) -> ProcessingRun | None: ...

    def next_run_number(self, import_id: UUID) -> int: ...

    def add(self, run: ProcessingRun) -> None: ...

    def save(self, run: ProcessingRun, *, expected_version: int) -> None: ...

    def claim_stale_batch(self, *, now: datetime, limit: int) -> Sequence[ProcessingRun]: ...

    def claim_queued_for_redispatch(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[ProcessingRun]: ...

    def list_dead_lettered(self, *, limit: int) -> Sequence[ProcessingRun]: ...


class OutboxRepositoryPort(Protocol):
    def by_id(self, message_id: UUID, *, for_update: bool = False) -> OutboxMessage | None: ...

    def by_deduplication_key(self, key: str) -> OutboxMessage | None: ...

    def add(self, message: OutboxMessage) -> None: ...

    def save(self, message: OutboxMessage, *, expected_version: int) -> None: ...

    def claim_due_batch(
        self, *, now: datetime, owner: str, lock_seconds: int, limit: int
    ) -> Sequence[OutboxMessage]: ...

    def recover_expired_locks(self, *, now: datetime, limit: int) -> Sequence[OutboxMessage]: ...


class UnitOfWorkPort(Protocol):
    imports: ImportRepositoryPort
    processing_runs: ProcessingRunRepositoryPort
    outbox: OutboxRepositoryPort

    def __enter__(self) -> UnitOfWorkPort: ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWorkPort]


class PublishStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    NONRETRYABLE_FAILURE = "NONRETRYABLE_FAILURE"


@dataclass(frozen=True, slots=True)
class PublishResult:
    status: PublishStatus
    error_code: str | None = None
    error_message: str | None = None


class ProcessingQueuePort(Protocol):
    def publish(self, message: ProcessingJobMessageV1) -> PublishResult: ...


@dataclass(frozen=True, slots=True)
class ProcessingContext:
    import_id: UUID
    processing_run_id: UUID
    run_number: int
    correlation_id: str
    effect_key: str
    source_file: SourceFile
    storage: ObjectStoragePort


class ProcessingOutcomeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    NONRETRYABLE_FAILURE = "NONRETRYABLE_FAILURE"


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    status: ProcessingOutcomeStatus
    code: str
    reason: str


class ProcessingHandlerPort(Protocol):
    def process(self, context: ProcessingContext) -> ProcessingOutcome: ...
