from __future__ import annotations

from io import BytesIO

from snax_import.adapters.db.memory import InMemoryDatabase, InMemoryUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage
from snax_import.application.import_registration import ImportRegistrationService, UploadRequest
from snax_import.application.processing.claim_job import ClaimJobService
from snax_import.domain.jobs import ProcessingJobMessageV1


def test_duplicate_delivery_produces_one_claim_and_one_processing_event() -> None:
    database = InMemoryDatabase()
    storage = InMemoryObjectStorage()

    def factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(database)

    registration = ImportRegistrationService(
        uow_factory=factory,
        storage=storage,
        max_upload_bytes=1024,
        processing_autostart=True,
    )
    created = registration.register(
        UploadRequest(
            stream=BytesIO(b"synthetic queue payload"),
            original_filename="synthetic.bin",
            media_type="application/octet-stream",
            idempotency_key="queue-idempotency-0001",
            correlation_id="queue-correlation-0001",
        )
    )
    outbox = next(iter(database.outbox.values()))
    message = ProcessingJobMessageV1.from_payload(outbox.payload)
    service = ClaimJobService(uow_factory=factory, lease_seconds=45)
    first = service.claim(message, worker_id="worker-1")
    second = service.claim(message, worker_id="worker-2")
    assert created.status.value == "QUEUED"
    assert first.claimed is True
    assert second.claimed is False
    assert second.result == "DUPLICATE_DELIVERY"
    assert len(database.runs) == 1
    assert [event.new_status.value for event in database.events[created.import_id]].count(
        "PROCESSING"
    ) == 1
