from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from snax_import.adapters.db.models import ImportModel, ImportStatusEventModel, SourceFileModel
from snax_import.domain.entities import Import, ImportStatusEvent, SourceFile
from snax_import.domain.errors import PersistenceConflict
from snax_import.domain.ports import ImportRepositoryPort
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


def _source_from_model(model: SourceFileModel) -> SourceFile:
    from snax_import.domain.entities import StorageStatus

    return SourceFile(
        id=model.id,
        sha256=Sha256Digest(model.sha256),
        object_key=ObjectKey(model.object_key),
        original_filename=OriginalFileName(model.original_filename),
        media_type=MediaType(model.media_type),
        size=FileSize(model.size_bytes),
        storage_status=StorageStatus(model.storage_status),
        created_at=model.created_at,
    )


def _import_from_model(model: ImportModel) -> Import:
    events = model.events
    return Import(
        id=model.id,
        source_file_id=model.source_file_id,
        status=ImportStatus(model.status),
        version=model.version,
        correlation_id=CorrelationId(model.correlation_id),
        idempotency_key=IdempotencyKey(model.idempotency_key),
        created_at=model.created_at,
        updated_at=model.updated_at,
        supplier_code=model.supplier_code,
        profile_code=model.profile_code,
        event_sequence=max((event.sequence for event in events), default=0),
    )


class SqlAlchemyImportRepository(ImportRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def _query(self) -> Select[tuple[ImportModel]]:
        return select(ImportModel).options(selectinload(ImportModel.events))

    def by_id(self, import_id: UUID) -> Import | None:
        model = self.session.scalar(self._query().where(ImportModel.id == import_id))
        return _import_from_model(model) if model is not None else None

    def by_idempotency(self, key: str) -> Import | None:
        model = self.session.scalar(self._query().where(ImportModel.idempotency_key == key))
        return _import_from_model(model) if model is not None else None

    def by_digest(self, digest: Sha256Digest) -> Import | None:
        model = self.session.scalar(
            self._query()
            .join(SourceFileModel, ImportModel.source_file_id == SourceFileModel.id)
            .where(SourceFileModel.sha256 == digest.value)
        )
        return _import_from_model(model) if model is not None else None

    def source_for_import(self, import_id: UUID) -> SourceFile | None:
        model = self.session.scalar(
            select(SourceFileModel)
            .join(ImportModel, ImportModel.source_file_id == SourceFileModel.id)
            .where(ImportModel.id == import_id)
        )
        return _source_from_model(model) if model is not None else None

    def save_registration(
        self, source_file: SourceFile, aggregate: Import, events: Sequence[ImportStatusEvent]
    ) -> None:
        source_model = SourceFileModel(
            id=source_file.id,
            sha256=source_file.sha256.value,
            object_key=source_file.object_key.value,
            original_filename=source_file.original_filename.value,
            media_type=source_file.media_type.value,
            size_bytes=source_file.size.value,
            storage_status=source_file.storage_status.value,
            created_at=source_file.created_at,
        )
        import_model = ImportModel(
            id=aggregate.id,
            source_file_id=aggregate.source_file_id,
            status=aggregate.status.value,
            version=aggregate.version,
            correlation_id=aggregate.correlation_id.value,
            idempotency_key=aggregate.idempotency_key.value,
            supplier_code=aggregate.supplier_code,
            profile_code=aggregate.profile_code,
            created_at=aggregate.created_at,
            updated_at=aggregate.updated_at,
        )
        self.session.add(source_model)
        self.session.add(import_model)
        self.session.add_all(
            ImportStatusEventModel(
                id=event.id,
                import_id=event.import_id,
                sequence=event.sequence,
                previous_status=event.previous_status.value
                if event.previous_status is not None
                else None,
                new_status=event.new_status.value,
                reason=event.reason,
                correlation_id=event.correlation_id.value,
                actor=event.actor,
                occurred_at=event.occurred_at,
            )
            for event in events
        )
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise PersistenceConflict() from exc

    def save_transition(
        self, aggregate: Import, event: ImportStatusEvent, expected_version: int
    ) -> None:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(ImportModel)
                .where(ImportModel.id == aggregate.id, ImportModel.version == expected_version)
                .values(
                    status=aggregate.status.value,
                    version=aggregate.version,
                    updated_at=aggregate.updated_at,
                )
            ),
        )
        if result.rowcount != 1:
            raise PersistenceConflict("Optimistic version conflict")
        self.session.add(
            ImportStatusEventModel(
                id=event.id,
                import_id=event.import_id,
                sequence=event.sequence,
                previous_status=event.previous_status.value
                if event.previous_status is not None
                else None,
                new_status=event.new_status.value,
                reason=event.reason,
                correlation_id=event.correlation_id.value,
                actor=event.actor,
                occurred_at=event.occurred_at,
            )
        )
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise PersistenceConflict() from exc
