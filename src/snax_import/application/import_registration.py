from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from snax_import.application.scheduling.schedule_import import enqueue_import
from snax_import.domain.entities import Import, ImportStatusEvent, SourceFile
from snax_import.domain.errors import (
    DuplicateFile,
    EmptyFile,
    FileTooLarge,
    IdempotencyConflict,
    PersistenceConflict,
)
from snax_import.domain.ports import ObjectStoragePort, UnitOfWorkFactory
from snax_import.domain.state_machine import ImportStatus
from snax_import.domain.value_objects import (
    CorrelationId,
    FileSize,
    IdempotencyKey,
    MediaType,
    ObjectKey,
    OriginalFileName,
    Sha256Digest,
)

_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class UploadRequest:
    stream: BinaryIO
    original_filename: str
    media_type: str
    idempotency_key: str
    correlation_id: str
    supplier_code: str | None = None
    profile_code: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    import_id: UUID
    status: ImportStatus
    created_at: datetime
    correlation_id: str
    replay: bool
    source: SourceFile


class ImportRegistrationService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        storage: ObjectStoragePort,
        max_upload_bytes: int,
        temp_directory: str | None = None,
        processing_autostart: bool = False,
    ) -> None:
        self.uow_factory = uow_factory
        self.storage = storage
        self.max_upload_bytes = max_upload_bytes
        self.temp_directory = temp_directory
        self.processing_autostart = processing_autostart

    def _read_to_temp(self, request: UploadRequest) -> tuple[Path, Sha256Digest, FileSize]:
        hasher = hashlib.sha256()
        total = 0
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b", prefix="snax-upload-", dir=self.temp_directory, delete=False
            ) as temp_file:
                path = Path(temp_file.name)
                while chunk := request.stream.read(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > self.max_upload_bytes:
                        raise FileTooLarge(total, self.max_upload_bytes)
                    hasher.update(chunk)
                    temp_file.write(chunk)
                if total == 0:
                    raise EmptyFile()
                return path, Sha256Digest(hasher.hexdigest()), FileSize(total)
        except Exception:
            if path is not None:
                path.unlink(missing_ok=True)
            raise

    def _existing_result(
        self, aggregate: Import, source: SourceFile, *, replay: bool
    ) -> RegistrationResult:
        return RegistrationResult(
            import_id=aggregate.id,
            status=aggregate.status,
            created_at=aggregate.created_at,
            correlation_id=aggregate.correlation_id.value,
            replay=replay,
            source=source,
        )

    def _precheck(
        self, *, idempotency_key: IdempotencyKey, digest: Sha256Digest
    ) -> RegistrationResult | None:
        with self.uow_factory() as uow:
            existing = uow.imports.by_idempotency(idempotency_key.value)
            if existing is not None:
                source = uow.imports.source_for_import(existing.id)
                if source is None:
                    raise PersistenceConflict("Импорт найден без source file")
                if source.sha256 != digest:
                    raise IdempotencyConflict(idempotency_key.value)
                return self._existing_result(existing, source, replay=True)
            duplicate = uow.imports.by_digest(digest)
            if duplicate is not None:
                source = uow.imports.source_for_import(duplicate.id)
                if source is None:
                    raise PersistenceConflict("Дубликат найден без source file")
                raise DuplicateFile(duplicate.id)
        return None

    def register(self, request: UploadRequest) -> RegistrationResult:
        idempotency_key = IdempotencyKey(request.idempotency_key)
        correlation_id = CorrelationId(request.correlation_id)
        original_filename = OriginalFileName(request.original_filename)
        media_type = MediaType(request.media_type or "application/octet-stream")
        path, digest, size = self._read_to_temp(request)
        object_key = ObjectKey.for_digest(digest)
        try:
            existing = self._precheck(idempotency_key=idempotency_key, digest=digest)
            if existing is not None:
                return existing

            with path.open("rb") as stream:
                self.storage.put_stream(
                    stream,
                    object_key=object_key,
                    digest=digest,
                    size=size.value,
                    media_type=media_type.value,
                    # Blob metadata must be content-invariant and ASCII-safe. The original
                    # filename belongs to the PostgreSQL source record because the same bytes
                    # can arrive under different (including Cyrillic) filenames.
                    metadata={"media-type": media_type.value},
                )

            source = SourceFile.create(
                sha256=digest,
                object_key=object_key,
                original_filename=original_filename,
                media_type=media_type,
                size=size,
            )
            aggregate = Import.create(
                source_file_id=source.id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                supplier_code=request.supplier_code,
                profile_code=request.profile_code,
            )
            events: list[ImportStatusEvent] = [
                aggregate.initial_event(reason="Upload принят и digest вычислен")
            ]
            transition = aggregate.transition(
                ImportStatus.STORED,
                reason="Immutable raw object сохранён и проверен",
                correlation_id=correlation_id,
            )
            aggregate = transition.aggregate
            events.append(transition.event)

            try:
                with self.uow_factory() as uow:
                    winner_by_key = uow.imports.by_idempotency(idempotency_key.value)
                    if winner_by_key is not None:
                        winner_source = uow.imports.source_for_import(winner_by_key.id)
                        if winner_source is None:
                            raise PersistenceConflict("Победивший импорт без source file")
                        if winner_source.sha256 != digest:
                            raise IdempotencyConflict(idempotency_key.value)
                        return self._existing_result(winner_by_key, winner_source, replay=True)
                    winner_by_digest = uow.imports.by_digest(digest)
                    if winner_by_digest is not None:
                        raise DuplicateFile(winner_by_digest.id)
                    uow.imports.save_registration(source, aggregate, events)
                    if self.processing_autostart:
                        scheduled = enqueue_import(
                            uow=uow,
                            aggregate=aggregate,
                            reason="PROCESSING_AUTOSTART",
                            actor="import-registration",
                            now=aggregate.updated_at,
                        )
                        aggregate = scheduled.aggregate
                    uow.commit()
            except (PersistenceConflict, IdempotencyConflict, DuplicateFile) as conflict:
                with self.uow_factory() as check_uow:
                    winner = check_uow.imports.by_idempotency(idempotency_key.value)
                    if winner is not None:
                        winner_source = check_uow.imports.source_for_import(winner.id)
                        if winner_source is not None and winner_source.sha256 == digest:
                            return self._existing_result(winner, winner_source, replay=True)
                        raise IdempotencyConflict(idempotency_key.value) from conflict
                    winner = check_uow.imports.by_digest(digest)
                    if winner is not None:
                        raise DuplicateFile(winner.id) from conflict
                # Never delete a content-addressed raw object synchronously after a database
                # conflict. Another concurrent request may already reference the same digest.
                # An unreferenced object is safer than deleting a referenced original and is
                # reclaimed only by a future grace-period garbage collector.
                raise conflict
            return RegistrationResult(
                import_id=aggregate.id,
                status=aggregate.status,
                created_at=aggregate.created_at,
                correlation_id=correlation_id.value,
                replay=False,
                source=source,
            )
        finally:
            path.unlink(missing_ok=True)

    def get(self, import_id: UUID) -> tuple[Import, SourceFile] | None:
        with self.uow_factory() as uow:
            aggregate = uow.imports.by_id(import_id)
            if aggregate is None:
                return None
            source = uow.imports.source_for_import(import_id)
            if source is None:
                return None
            return aggregate, source
