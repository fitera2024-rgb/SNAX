from __future__ import annotations

from collections.abc import Sequence
from threading import RLock
from typing import cast
from uuid import UUID

from snax_import.domain.entities import Import, ImportStatusEvent, SourceFile
from snax_import.domain.errors import PersistenceConflict
from snax_import.domain.ports import ImportRepositoryPort, UnitOfWorkPort
from snax_import.domain.value_objects import Sha256Digest


class InMemoryDatabase:
    def __init__(self) -> None:
        self.sources: dict[UUID, SourceFile] = {}
        self.imports: dict[UUID, Import] = {}
        self.events: dict[UUID, list[ImportStatusEvent]] = {}
        self.lock = RLock()


class InMemoryImportRepository(ImportRepositoryPort):
    def __init__(self, database: InMemoryDatabase) -> None:
        self.database = database
        self.pending: tuple[SourceFile, Import, Sequence[ImportStatusEvent]] | None = None

    def by_id(self, import_id: UUID) -> Import | None:
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

    def save_registration(
        self, source_file: SourceFile, aggregate: Import, events: Sequence[ImportStatusEvent]
    ) -> None:
        self.pending = (source_file, aggregate, events)


class InMemoryUnitOfWork:
    def __init__(self, database: InMemoryDatabase) -> None:
        self.database = database
        self.imports = InMemoryImportRepository(database)

    def __enter__(self) -> UnitOfWorkPort:
        return cast(UnitOfWorkPort, self)

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.imports.pending = None

    def commit(self) -> None:
        pending = self.imports.pending
        if pending is None:
            return
        source_file, aggregate, events = pending
        with self.database.lock:
            if any(
                item.idempotency_key == aggregate.idempotency_key
                for item in self.database.imports.values()
            ):
                raise PersistenceConflict()
            if any(item.sha256 == source_file.sha256 for item in self.database.sources.values()):
                raise PersistenceConflict()
            self.database.sources[source_file.id] = source_file
            self.database.imports[aggregate.id] = aggregate
            self.database.events[aggregate.id] = list(events)
        self.imports.pending = None

    def rollback(self) -> None:
        self.imports.pending = None
