from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from threading import RLock
from typing import cast
from uuid import UUID

from snax_import.domain.entities import Import, ImportStatusEvent, SourceFile
from snax_import.domain.errors import PersistenceConflict
from snax_import.domain.outbox import OutboxMessage, OutboxStatus
from snax_import.domain.ports import (
    ImportRepositoryPort,
    OutboxRepositoryPort,
    ProcessingRunRepositoryPort,
    UnitOfWorkPort,
)
from snax_import.domain.processing import ProcessingRun, ProcessingRunStatus
from snax_import.domain.state_machine import ImportStatus
from snax_import.domain.value_objects import Sha256Digest


class InMemoryDatabase:
    def __init__(self) -> None:
        self.sources: dict[UUID, SourceFile] = {}
        self.imports: dict[UUID, Import] = {}
        self.events: dict[UUID, list[ImportStatusEvent]] = {}
        self.runs: dict[UUID, ProcessingRun] = {}
        self.outbox: dict[UUID, OutboxMessage] = {}
        self.lock = RLock()


class InMemoryImportRepository(ImportRepositoryPort):
    def __init__(self, database: InMemoryDatabase) -> None:
        self.database = database
        self.pending_registration: tuple[SourceFile, Import, Sequence[ImportStatusEvent]] | None = (
            None
        )
        self.pending_transitions: list[tuple[Import, ImportStatusEvent, int]] = []

    def by_id(self, import_id: UUID, *, for_update: bool = False) -> Import | None:
        del for_update
        with self.database.lock:
            return self.database.imports.get(import_id)

    def by_idempotency(self, key: str) -> Import | None:
        with self.database.lock:
            return next(
                (
                    item
                    for item in self.database.imports.values()
                    if item.idempotency_key.value == key
                ),
                None,
            )

    def by_digest(self, digest: Sha256Digest) -> Import | None:
        with self.database.lock:
            source_ids = {
                source.id for source in self.database.sources.values() if source.sha256 == digest
            }
            return next(
                (
                    item
                    for item in self.database.imports.values()
                    if item.source_file_id in source_ids
                ),
                None,
            )

    def source_for_import(self, import_id: UUID) -> SourceFile | None:
        with self.database.lock:
            item = self.database.imports.get(import_id)
            return self.database.sources.get(item.source_file_id) if item is not None else None

    def claim_stored_batch(self, *, limit: int) -> Sequence[Import]:
        with self.database.lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self.database.imports.values()
                        if item.status is ImportStatus.STORED
                    ),
                    key=lambda item: (item.created_at, item.id),
                )[:limit]
            )

    def save_registration(
        self, source_file: SourceFile, aggregate: Import, events: Sequence[ImportStatusEvent]
    ) -> None:
        self.pending_registration = (source_file, aggregate, events)

    def save_transition(
        self, aggregate: Import, event: ImportStatusEvent, expected_version: int
    ) -> None:
        self.pending_transitions.append((aggregate, event, expected_version))


class InMemoryProcessingRunRepository(ProcessingRunRepositoryPort):
    def __init__(self, database: InMemoryDatabase) -> None:
        self.database = database
        self.pending_add: list[ProcessingRun] = []
        self.pending_save: list[tuple[ProcessingRun, int]] = []

    def _view(self) -> dict[UUID, ProcessingRun]:
        result = dict(self.database.runs)
        result.update({run.id: run for run in self.pending_add})
        result.update({run.id: run for run, _ in self.pending_save})
        return result

    def by_id(self, run_id: UUID, *, for_update: bool = False) -> ProcessingRun | None:
        del for_update
        with self.database.lock:
            return self._view().get(run_id)

    def active_for_import(
        self, import_id: UUID, *, for_update: bool = False
    ) -> ProcessingRun | None:
        del for_update
        with self.database.lock:
            return next(
                (
                    run
                    for run in self._view().values()
                    if run.import_id == import_id
                    and run.status in {ProcessingRunStatus.QUEUED, ProcessingRunStatus.PROCESSING}
                ),
                None,
            )

    def latest_for_import(
        self, import_id: UUID, *, for_update: bool = False
    ) -> ProcessingRun | None:
        del for_update
        with self.database.lock:
            candidates = [run for run in self._view().values() if run.import_id == import_id]
            return max(candidates, key=lambda run: run.run_number, default=None)

    def next_run_number(self, import_id: UUID) -> int:
        with self.database.lock:
            return (
                max(
                    (run.run_number for run in self._view().values() if run.import_id == import_id),
                    default=0,
                )
                + 1
            )

    def add(self, run: ProcessingRun) -> None:
        self.pending_add.append(run)

    def save(self, run: ProcessingRun, *, expected_version: int) -> None:
        self.pending_save.append((run, expected_version))

    def claim_stale_batch(self, *, now: datetime, limit: int) -> Sequence[ProcessingRun]:
        with self.database.lock:
            return tuple(
                sorted(
                    (
                        run
                        for run in self._view().values()
                        if run.status is ProcessingRunStatus.PROCESSING
                        and run.lease_expires_at is not None
                        and run.lease_expires_at <= now
                    ),
                    key=lambda run: (run.lease_expires_at or now, run.id),
                )[:limit]
            )

    def claim_queued_for_redispatch(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[ProcessingRun]:
        with self.database.lock:
            return tuple(
                sorted(
                    (
                        run
                        for run in self._view().values()
                        if run.status is ProcessingRunStatus.QUEUED
                        and (run.last_dispatched_at or run.queued_at) < older_than
                    ),
                    key=lambda run: (run.queued_at, run.id),
                )[:limit]
            )

    def list_dead_lettered(self, *, limit: int) -> Sequence[ProcessingRun]:
        with self.database.lock:
            return tuple(
                sorted(
                    (
                        run
                        for run in self._view().values()
                        if run.status is ProcessingRunStatus.DEAD_LETTERED
                    ),
                    key=lambda run: run.dead_lettered_at or run.updated_at,
                    reverse=True,
                )[:limit]
            )


class InMemoryOutboxRepository(OutboxRepositoryPort):
    def __init__(self, database: InMemoryDatabase) -> None:
        self.database = database
        self.pending_add: list[OutboxMessage] = []
        self.pending_save: list[tuple[OutboxMessage, int]] = []

    def _view(self) -> dict[UUID, OutboxMessage]:
        result = dict(self.database.outbox)
        result.update({item.id: item for item in self.pending_add})
        result.update({item.id: item for item, _ in self.pending_save})
        return result

    def by_id(self, message_id: UUID, *, for_update: bool = False) -> OutboxMessage | None:
        del for_update
        with self.database.lock:
            return self._view().get(message_id)

    def by_deduplication_key(self, key: str) -> OutboxMessage | None:
        with self.database.lock:
            return next(
                (item for item in self._view().values() if item.deduplication_key == key), None
            )

    def add(self, message: OutboxMessage) -> None:
        self.pending_add.append(message)

    def save(self, message: OutboxMessage, *, expected_version: int) -> None:
        self.pending_save.append((message, expected_version))

    def claim_due_batch(
        self, *, now: datetime, owner: str, lock_seconds: int, limit: int
    ) -> Sequence[OutboxMessage]:
        due = sorted(
            (
                item
                for item in self._view().values()
                if item.status is OutboxStatus.PENDING and item.available_at <= now
            ),
            key=lambda item: (item.available_at, item.id),
        )[:limit]
        claimed = [item.claim(owner=owner, now=now, lock_seconds=lock_seconds) for item in due]
        self.pending_save.extend((item, item.version - 1) for item in claimed)
        return claimed

    def recover_expired_locks(self, *, now: datetime, limit: int) -> Sequence[OutboxMessage]:
        expired = sorted(
            (
                item
                for item in self._view().values()
                if item.status is OutboxStatus.PUBLISHING
                and item.lock_expires_at is not None
                and item.lock_expires_at <= now
            ),
            key=lambda item: (item.lock_expires_at or now, item.id),
        )[:limit]
        recovered = [item.recover_expired(now=now) for item in expired]
        self.pending_save.extend((item, item.version - 1) for item in recovered)
        return recovered


class InMemoryUnitOfWork:
    def __init__(self, database: InMemoryDatabase) -> None:
        self.database = database
        self.imports = InMemoryImportRepository(database)
        self.processing_runs = InMemoryProcessingRunRepository(database)
        self.outbox = InMemoryOutboxRepository(database)

    def __enter__(self) -> UnitOfWorkPort:
        return cast(UnitOfWorkPort, self)

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._clear()

    def commit(self) -> None:
        with self.database.lock:
            sources = dict(self.database.sources)
            imports = dict(self.database.imports)
            events = {key: list(value) for key, value in self.database.events.items()}
            runs = dict(self.database.runs)
            outbox = dict(self.database.outbox)

            pending = self.imports.pending_registration
            if pending is not None:
                source_file, aggregate, new_events = pending
                if any(
                    item.idempotency_key == aggregate.idempotency_key for item in imports.values()
                ):
                    raise PersistenceConflict()
                if any(item.sha256 == source_file.sha256 for item in sources.values()):
                    raise PersistenceConflict()
                sources[source_file.id] = source_file
                imports[aggregate.id] = aggregate
                events[aggregate.id] = list(new_events)

            for aggregate, event, expected_version in self.imports.pending_transitions:
                current_import = imports.get(aggregate.id)
                if current_import is None or current_import.version != expected_version:
                    raise PersistenceConflict("Optimistic version conflict")
                imports[aggregate.id] = aggregate
                events.setdefault(aggregate.id, []).append(event)

            # Existing active runs are completed before a retry run is inserted in the
            # same transaction. Apply optimistic saves first to mirror SQL flush order.
            for run, expected_version in self.processing_runs.pending_save:
                current_run = runs.get(run.id)
                if current_run is None or current_run.version != expected_version:
                    raise PersistenceConflict("ProcessingRun optimistic version conflict")
                runs[run.id] = run

            for run in self.processing_runs.pending_add:
                if any(
                    item.import_id == run.import_id and item.run_number == run.run_number
                    for item in runs.values()
                ):
                    raise PersistenceConflict("Duplicate run number")
                if run.status in {
                    ProcessingRunStatus.QUEUED,
                    ProcessingRunStatus.PROCESSING,
                } and any(
                    item.import_id == run.import_id
                    and item.status in {ProcessingRunStatus.QUEUED, ProcessingRunStatus.PROCESSING}
                    for item in runs.values()
                ):
                    raise PersistenceConflict("Active run already exists")
                runs[run.id] = run
            for message in self.outbox.pending_add:
                if any(
                    item.deduplication_key == message.deduplication_key for item in outbox.values()
                ):
                    raise PersistenceConflict("Duplicate outbox deduplication key")
                outbox[message.id] = message
            for message, expected_version in self.outbox.pending_save:
                current_outbox = outbox.get(message.id)
                if current_outbox is None or current_outbox.version != expected_version:
                    raise PersistenceConflict("Outbox optimistic version conflict")
                outbox[message.id] = message

            self.database.sources = sources
            self.database.imports = imports
            self.database.events = events
            self.database.runs = runs
            self.database.outbox = outbox
        self._clear()

    def rollback(self) -> None:
        self._clear()

    def _clear(self) -> None:
        self.imports.pending_registration = None
        self.imports.pending_transitions.clear()
        self.processing_runs.pending_add.clear()
        self.processing_runs.pending_save.clear()
        self.outbox.pending_add.clear()
        self.outbox.pending_save.clear()
