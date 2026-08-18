from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest

from snax_import.adapters.db.memory import InMemoryDatabase, InMemoryUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage
from snax_import.application.import_registration import ImportRegistrationService, UploadRequest
from snax_import.domain.errors import DuplicateFile, IdempotencyConflict
from snax_import.domain.state_machine import ImportStatus


def build_service(
    max_upload_bytes: int = 1024 * 1024,
) -> tuple[ImportRegistrationService, InMemoryDatabase, InMemoryObjectStorage]:
    database = InMemoryDatabase()
    storage = InMemoryObjectStorage()

    def factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(database)

    return (
        ImportRegistrationService(
            uow_factory=factory,
            storage=storage,
            max_upload_bytes=max_upload_bytes,
        ),
        database,
        storage,
    )


def request(payload: bytes, key: str, filename: str = "price.xlsx") -> UploadRequest:
    return UploadRequest(
        stream=BytesIO(payload),
        original_filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        idempotency_key=key,
        correlation_id="correlation-001",
    )


def test_registration_is_streamed_and_idempotent() -> None:
    service, database, storage = build_service()
    first = service.register(request(b"payload", "idempotency-0001"))
    replay = service.register(request(b"payload", "idempotency-0001", "renamed.xlsx"))
    assert first.status is ImportStatus.STORED
    assert replay.replay is True
    assert replay.import_id == first.import_id
    assert len(database.imports) == 1
    assert storage.object_count() == 1


def test_exact_duplicate_and_idempotency_conflict_are_distinct() -> None:
    service, database, storage = build_service()
    first = service.register(request(b"payload", "idempotency-0002"))
    with pytest.raises(DuplicateFile) as duplicate:
        service.register(request(b"payload", "idempotency-0003"))
    assert duplicate.value.existing_import_id == first.import_id
    with pytest.raises(IdempotencyConflict):
        service.register(request(b"other", "idempotency-0002"))
    assert len(database.imports) == 1
    assert storage.object_count() == 1


def test_concurrent_duplicate_registration_has_one_import_and_one_object() -> None:
    service, database, storage = build_service()

    def submit(index: int):
        try:
            return service.register(request(b"same payload", f"race-idempotency-{index:04d}"))
        except DuplicateFile as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, (1, 2)))
    assert sum(not isinstance(result, DuplicateFile) for result in results) == 1
    assert sum(isinstance(result, DuplicateFile) for result in results) == 1
    assert len(database.imports) == 1
    assert len(database.sources) == 1
    assert storage.object_count() == 1
