from __future__ import annotations

import os
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from snax_import.adapters.db.models import ImportModel, OutboxMessageModel, ProcessingRunModel
from snax_import.adapters.db.session import create_database_engine, create_session_factory
from snax_import.adapters.db.uow import SqlAlchemyUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage
from snax_import.application.import_registration import ImportRegistrationService, UploadRequest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
def test_schedule_transition_run_and_outbox_are_one_postgresql_transaction() -> None:
    engine = create_database_engine(os.environ["TEST_DATABASE_URL"])
    factory = create_session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory)

    marker = uuid4().hex
    service = ImportRegistrationService(
        uow_factory=uow_factory,
        storage=InMemoryObjectStorage(),
        max_upload_bytes=1024,
        processing_autostart=True,
    )
    created = service.register(
        UploadRequest(
            stream=BytesIO(f"atomic-{marker}".encode()),
            original_filename="synthetic.bin",
            media_type="application/octet-stream",
            idempotency_key=f"atomic-{marker}",
            correlation_id=f"corr-{marker}",
        )
    )
    with Session(engine) as session:
        aggregate = session.get(ImportModel, created.import_id)
        assert aggregate is not None and aggregate.status == "QUEUED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProcessingRunModel)
                .where(ProcessingRunModel.import_id == created.import_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxMessageModel)
                .where(OutboxMessageModel.aggregate_id == created.import_id)
            )
            == 1
        )
