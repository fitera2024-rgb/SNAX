from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from snax_import.adapters.db.models import OutboxMessageModel, ProcessingRunModel
from snax_import.adapters.db.session import create_database_engine, create_session_factory
from snax_import.adapters.db.uow import SqlAlchemyUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage
from snax_import.application.import_registration import ImportRegistrationService, UploadRequest
from snax_import.application.outbox.publish_messages import OutboxDispatcherService
from snax_import.application.processing.claim_job import ClaimJobService
from snax_import.application.processing.fail_job import FailJobService
from snax_import.application.processing.heartbeat import HeartbeatJobService
from snax_import.application.processing.recover_stale import RecoverStaleJobsService
from snax_import.application.scheduling.retry_import import ManualRetryCommand, RetryImportService
from snax_import.domain.errors import DomainError
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.ports import ProcessingQueuePort, PublishResult, PublishStatus
from snax_import.domain.processing import ProcessingRunStatus
from snax_import.domain.retry import RetryPolicy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required"
    ),
]


def _factory():
    engine = create_database_engine(os.environ["TEST_DATABASE_URL"])
    session_factory = create_session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return engine, uow_factory


def _register(uow_factory, marker: str):
    service = ImportRegistrationService(
        uow_factory=uow_factory,
        storage=InMemoryObjectStorage(),
        max_upload_bytes=1024,
        processing_autostart=True,
    )
    return service.register(
        UploadRequest(
            stream=BytesIO(f"postgres-queue-{marker}".encode()),
            original_filename="synthetic.bin",
            media_type="application/octet-stream",
            idempotency_key=f"postgres-queue-{marker}",
            correlation_id=f"postgres-queue-{marker}",
        )
    )


def _policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        base_seconds=1,
        max_seconds=10,
        multiplier=2,
        jitter_ratio=0,
        random_value=lambda: 0.5,
    )


class RecordingQueue(ProcessingQueuePort):
    def __init__(self) -> None:
        self.messages: list[ProcessingJobMessageV1] = []
        self.lock = Lock()

    def publish(self, message: ProcessingJobMessageV1) -> PublishResult:
        with self.lock:
            self.messages.append(message)
        return PublishResult(PublishStatus.ACCEPTED)


def test_two_postgresql_dispatchers_publish_one_outbox_row() -> None:
    _, uow_factory = _factory()
    marker = uuid4().hex
    created = _register(uow_factory, marker)
    queue = RecordingQueue()

    def dispatch(owner: str) -> int:
        return OutboxDispatcherService(
            uow_factory=uow_factory,
            queue=queue,
            dispatcher_id=owner,
            batch_size=1,
            lock_seconds=30,
            max_publish_attempts=3,
            retry_base_seconds=1,
            retry_max_seconds=10,
        ).dispatch_once()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(dispatch, ("dispatcher-a", "dispatcher-b")))
    assert sum(claimed) == 1
    assert len(queue.messages) == 1
    with uow_factory() as uow:
        outbox = uow.outbox.by_deduplication_key(f"process:{queue.messages[0].processing_run_id}:1")
    assert outbox is not None and outbox.status.value == "PUBLISHED"
    assert outbox.aggregate_id == created.import_id


def test_manual_retry_race_creates_one_new_postgresql_run() -> None:
    engine, uow_factory = _factory()
    marker = uuid4().hex
    created = _register(uow_factory, marker)
    with Session(engine) as session:
        payload = session.scalar(
            select(OutboxMessageModel.payload).where(
                OutboxMessageModel.aggregate_id == created.import_id
            )
        )
    assert payload is not None
    message = ProcessingJobMessageV1.from_payload(dict(payload))
    claim = ClaimJobService(uow_factory=uow_factory, lease_seconds=30).claim(
        message, worker_id="worker-race"
    )
    assert claim.lease_token is not None
    FailJobService(uow_factory=uow_factory, retry_policy=_policy()).fail(
        processing_run_id=message.processing_run_id,
        lease_token=claim.lease_token,
        worker_id="worker-race",
        code="NONRETRYABLE_TEST",
        reason="synthetic",
        retryable=False,
    )
    command = ManualRetryCommand(
        import_id=created.import_id,
        actor="integration-operator",
        reason="race test",
        correlation_id=f"manual-race-{marker}",
    )
    barrier = Barrier(2)

    def retry() -> str:
        barrier.wait()
        return str(RetryImportService(uow_factory).retry(command).run.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(retry), pool.submit(retry))
        results = [future.result() for future in futures]
    assert len(set(results)) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProcessingRunModel)
                .where(ProcessingRunModel.import_id == created.import_id)
            )
            == 2
        )


def test_heartbeat_vs_sweeper_never_creates_two_active_runs() -> None:
    engine, uow_factory = _factory()
    marker = uuid4().hex
    created = _register(uow_factory, marker)
    with Session(engine) as session:
        model = session.scalar(
            select(ProcessingRunModel).where(ProcessingRunModel.import_id == created.import_id)
        )
        outbox = session.scalar(
            select(OutboxMessageModel).where(OutboxMessageModel.aggregate_id == created.import_id)
        )
    assert model is not None and outbox is not None
    message = ProcessingJobMessageV1.from_payload(dict(outbox.payload))
    claim = ClaimJobService(
        uow_factory=uow_factory,
        lease_seconds=30,
        clock=lambda: model.queued_at,
    ).claim(message, worker_id="worker-heartbeat")
    assert claim.lease_token is not None
    barrier = Barrier(2)

    def heartbeat() -> str:
        barrier.wait()
        try:
            HeartbeatJobService(
                uow_factory=uow_factory,
                lease_seconds=30,
                clock=lambda: model.queued_at + timedelta(seconds=29),
            ).heartbeat(
                processing_run_id=model.id,
                lease_token=claim.lease_token,
                worker_id="worker-heartbeat",
            )
            return "heartbeat"
        except DomainError:
            return "sweeper-won"

    def sweep() -> str:
        barrier.wait()
        result = RecoverStaleJobsService(
            uow_factory=uow_factory,
            retry_policy=_policy(),
            clock=lambda: model.queued_at + timedelta(seconds=31),
        ).recover_once(limit=10)
        return f"swept-{result.timed_out}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(heartbeat), pool.submit(sweep))
        results = [future.result() for future in futures]
    assert results[0] in {"heartbeat", "sweeper-won"}
    with Session(engine) as session:
        active = session.scalar(
            select(func.count())
            .select_from(ProcessingRunModel)
            .where(
                ProcessingRunModel.import_id == created.import_id,
                ProcessingRunModel.status.in_(["QUEUED", "PROCESSING"]),
            )
        )
        all_runs = session.scalars(
            select(ProcessingRunModel).where(ProcessingRunModel.import_id == created.import_id)
        ).all()
    assert active <= 1
    assert sum(run.status == ProcessingRunStatus.QUEUED.value for run in all_runs) <= 1
    assert len(all_runs) <= 2
