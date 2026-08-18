from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from snax_import.adapters.db.base import Base
from snax_import.adapters.db.models import ImportStatusEventModel
from snax_import.adapters.db.repositories import SqlAlchemyImportRepository
from snax_import.domain.entities import Import, SourceFile
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

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
def test_postgresql_repository_round_trip_and_event_ordering() -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    digest = Sha256Digest("b" * 64)
    source = SourceFile.create(
        sha256=digest,
        object_key=ObjectKey.for_digest(digest),
        original_filename=OriginalFileName("roundtrip.xlsx"),
        media_type=MediaType("application/octet-stream"),
        size=FileSize(7),
        now=now,
    )
    aggregate = Import.create(
        source_file_id=source.id,
        correlation_id=CorrelationId("roundtrip-correlation"),
        idempotency_key=IdempotencyKey("roundtrip-idempotency"),
        now=now,
    )
    first = aggregate.initial_event(reason="created")
    transition = aggregate.transition(ImportStatus.STORED, reason="stored", now=now)
    with Session(engine) as session:
        repository = SqlAlchemyImportRepository(session)
        repository.save_registration(source, transition.aggregate, [first, transition.event])
        session.commit()
        loaded = repository.by_id(aggregate.id)
        assert loaded is not None
        assert loaded.status is ImportStatus.STORED
        assert [
            event.sequence
            for event in session.scalars(
                select(ImportStatusEventModel)
                .where(ImportStatusEventModel.import_id == aggregate.id)
                .order_by(ImportStatusEventModel.sequence)
            ).all()
        ] == [1, 2]
