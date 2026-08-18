from __future__ import annotations

from io import BytesIO

from snax_import.adapters.db.memory import InMemoryDatabase, InMemoryUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage
from snax_import.application.import_registration import ImportRegistrationService, UploadRequest
from snax_import.application.outbox.publish_messages import OutboxDispatcherService
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.outbox import OutboxStatus
from snax_import.domain.ports import ProcessingQueuePort, PublishResult, PublishStatus


class RecordingQueue(ProcessingQueuePort):
    def __init__(self, result: PublishResult) -> None:
        self.result = result
        self.messages: list[ProcessingJobMessageV1] = []

    def publish(self, message: ProcessingJobMessageV1) -> PublishResult:
        self.messages.append(message)
        return self.result


def _dispatcher(
    result: PublishResult,
) -> tuple[InMemoryDatabase, RecordingQueue, OutboxDispatcherService]:
    database = InMemoryDatabase()

    def factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(database)

    ImportRegistrationService(
        uow_factory=factory,
        storage=InMemoryObjectStorage(),
        max_upload_bytes=1024,
        processing_autostart=True,
    ).register(
        UploadRequest(
            stream=BytesIO(b"synthetic outbox payload"),
            original_filename="synthetic.bin",
            media_type="application/octet-stream",
            idempotency_key="dispatcher-idempotency-0001",
            correlation_id="dispatcher-correlation-0001",
        )
    )
    queue = RecordingQueue(result)
    service = OutboxDispatcherService(
        uow_factory=factory,
        queue=queue,
        dispatcher_id="dispatcher-a",
        batch_size=10,
        lock_seconds=30,
        max_publish_attempts=3,
        retry_base_seconds=1,
        retry_max_seconds=10,
    )
    return database, queue, service


def test_dispatcher_publishes_outside_claim_transaction_and_marks_durable_state() -> None:
    database, queue, dispatcher = _dispatcher(PublishResult(PublishStatus.ACCEPTED))
    assert dispatcher.dispatch_once() == 1
    assert len(queue.messages) == 1
    assert next(iter(database.outbox.values())).status is OutboxStatus.PUBLISHED
    assert next(iter(database.runs.values())).last_dispatched_at is not None


def test_dispatcher_releases_retryable_failure() -> None:
    database, _, dispatcher = _dispatcher(
        PublishResult(PublishStatus.RETRYABLE_FAILURE, "BROKER_UNAVAILABLE", "temporary")
    )
    assert dispatcher.dispatch_once() == 1
    outbox = next(iter(database.outbox.values()))
    assert outbox.status is OutboxStatus.PENDING
    assert outbox.publish_attempts == 1
    assert outbox.last_error_code == "BROKER_UNAVAILABLE"
