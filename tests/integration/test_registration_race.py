from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from snax_import.adapters.db.models import ImportModel, SourceFileModel
from snax_import.adapters.db.session import create_database_engine, create_session_factory
from snax_import.adapters.db.uow import SqlAlchemyUnitOfWork
from snax_import.adapters.storage.s3 import S3ObjectStorage
from snax_import.application.import_registration import ImportRegistrationService, UploadRequest
from snax_import.domain.errors import DuplicateFile
from snax_import.domain.value_objects import ObjectKey, Sha256Digest

pytestmark = pytest.mark.integration

_REQUIRED_ENV = (
    "TEST_DATABASE_URL",
    "TEST_S3_ENDPOINT",
    "TEST_S3_ACCESS_KEY",
    "TEST_S3_SECRET_KEY",
    "TEST_S3_BUCKET",
)


def _integration_available() -> bool:
    return all(os.environ.get(name) for name in _REQUIRED_ENV)


def _build_service() -> tuple[ImportRegistrationService, S3ObjectStorage]:
    engine = create_database_engine(os.environ["TEST_DATABASE_URL"])
    session_factory = create_session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    storage = S3ObjectStorage(
        endpoint=os.environ["TEST_S3_ENDPOINT"],
        access_key=os.environ["TEST_S3_ACCESS_KEY"],
        secret_key=os.environ["TEST_S3_SECRET_KEY"],
        bucket=os.environ["TEST_S3_BUCKET"],
    )
    return (
        ImportRegistrationService(
            uow_factory=uow_factory,
            storage=storage,
            max_upload_bytes=1024 * 1024,
        ),
        storage,
    )


@pytest.mark.skipif(not _integration_available(), reason="PostgreSQL and MinIO settings are required")
def test_concurrent_duplicate_registration_creates_one_import_and_one_object() -> None:
    payload = f"postgres-minio-race-{uuid4()}".encode()
    digest = Sha256Digest(hashlib.sha256(payload).hexdigest())
    object_key = ObjectKey.for_digest(digest)
    barrier = Barrier(2)

    def register(index: int):
        service, _ = _build_service()
        barrier.wait(timeout=10)
        try:
            return service.register(
                UploadRequest(
                    stream=BytesIO(payload),
                    original_filename=f"race-{index}.bin",
                    media_type="application/octet-stream",
                    idempotency_key=f"race-{uuid4()}",
                    correlation_id=f"race-correlation-{index}",
                )
            )
        except DuplicateFile as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, (1, 2)))

    winners = [result for result in results if not isinstance(result, DuplicateFile)]
    losers = [result for result in results if isinstance(result, DuplicateFile)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].existing_import_id == winners[0].import_id

    engine = create_database_engine(os.environ["TEST_DATABASE_URL"])
    with Session(engine) as session:
        source_count = session.scalar(
            select(func.count()).select_from(SourceFileModel).where(SourceFileModel.sha256 == digest.value)
        )
        import_count = session.scalar(
            select(func.count())
            .select_from(ImportModel)
            .join(SourceFileModel, ImportModel.source_file_id == SourceFileModel.id)
            .where(SourceFileModel.sha256 == digest.value)
        )
    assert source_count == 1
    assert import_count == 1

    _, storage = _build_service()
    listed = storage.client.list_objects_v2(
        Bucket=os.environ["TEST_S3_BUCKET"],
        Prefix=object_key.value,
    )
    keys = [item["Key"] for item in listed.get("Contents", [])]
    assert keys == [object_key.value]
    storage.verify_digest(object_key, digest)

    restarted_service, _ = _build_service()
    restored = restarted_service.get(winners[0].import_id)
    assert restored is not None
    aggregate, source = restored
    assert aggregate.id == winners[0].import_id
    assert source.sha256 == digest
