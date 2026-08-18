from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from io import BytesIO

from snax_import.adapters.db.memory import InMemoryDatabase, InMemoryUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage
from snax_import.application.import_registration import ImportRegistrationService, UploadRequest
from snax_import.application.processing.claim_job import ClaimJobService
from snax_import.application.processing.fail_job import FailJobService
from snax_import.application.processing.recover_stale import (
    RecoverStaleJobsService,
    RedispatchQueuedJobsService,
)
from snax_import.application.scheduling.retry_import import ManualRetryCommand, RetryImportService
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.processing import ProcessingRunStatus
from snax_import.domain.retry import RetryPolicy
from snax_import.domain.state_machine import ImportStatus


def _queue() -> tuple[InMemoryDatabase, Callable[[], InMemoryUnitOfWork]]:
    database = InMemoryDatabase()

    def factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(database)

    service = ImportRegistrationService(
        uow_factory=factory,
        storage=InMemoryObjectStorage(),
        max_upload_bytes=1024,
        processing_autostart=True,
    )
    service.register(
        UploadRequest(
            stream=BytesIO(b"synthetic recovery payload"),
            original_filename="synthetic.bin",
            media_type="application/octet-stream",
            idempotency_key="recovery-idempotency-0001",
            correlation_id="recovery-correlation-0001",
        )
    )
    return database, factory


def _policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        base_seconds=5,
        max_seconds=60,
        multiplier=2,
        jitter_ratio=0,
        random_value=lambda: 0.5,
    )


def test_stale_run_is_timed_out_and_retried_atomically() -> None:
    database, factory = _queue()
    message = ProcessingJobMessageV1.from_payload(next(iter(database.outbox.values())).payload)
    queued = database.runs[message.processing_run_id]
    claim = ClaimJobService(
        uow_factory=factory,
        lease_seconds=30,
        clock=lambda: queued.queued_at,
    ).claim(message, worker_id="worker-a")
    assert claim.claimed

    result = RecoverStaleJobsService(
        uow_factory=factory,
        retry_policy=_policy(),
        clock=lambda: queued.queued_at + timedelta(seconds=31),
    ).recover_once(limit=10)

    assert result.timed_out == 1
    assert result.retries == 1
    assert database.runs[queued.id].status is ProcessingRunStatus.TIMED_OUT
    retry = next(run for run in database.runs.values() if run.id != queued.id)
    assert retry.retry_of_run_id == queued.id
    assert retry.status is ProcessingRunStatus.QUEUED
    assert database.imports[queued.import_id].status is ImportStatus.QUEUED
    assert len(database.outbox) == 2


def test_queued_run_redispatch_preserves_logical_run() -> None:
    database, factory = _queue()
    run = next(iter(database.runs.values()))
    count = RedispatchQueuedJobsService(
        uow_factory=factory,
        redelivery_after_seconds=30,
        clock=lambda: run.queued_at + timedelta(seconds=31),
    ).redispatch_once(limit=10)

    durable = database.runs[run.id]
    assert count == 1
    assert len(database.runs) == 1
    assert durable.dispatch_generation == 2
    assert len(database.outbox) == 2
    assert {item.processing_run_id for item in database.outbox.values()} == {run.id}


def test_manual_retry_is_idempotent_and_preserves_failed_run() -> None:
    database, factory = _queue()
    message = ProcessingJobMessageV1.from_payload(next(iter(database.outbox.values())).payload)
    claim = ClaimJobService(uow_factory=factory, lease_seconds=30).claim(
        message, worker_id="worker-a"
    )
    assert claim.lease_token is not None
    failed = FailJobService(uow_factory=factory, retry_policy=_policy()).fail(
        processing_run_id=message.processing_run_id,
        lease_token=claim.lease_token,
        worker_id="worker-a",
        code="INVALID_SOURCE",
        reason="synthetic nonretryable failure",
        retryable=False,
    )
    assert failed.dead_lettered
    command = ManualRetryCommand(
        import_id=message.import_id,
        actor="operator@example.test",
        reason="corrected configuration",
        correlation_id="manual-command-0001",
    )
    service = RetryImportService(factory)
    first = service.retry(command)
    replay = service.retry(command)

    assert replay.run.id == first.run.id
    assert replay.outbox.id == first.outbox.id
    assert first.run.retry_of_run_id == failed.run.id
    assert len(database.runs) == 2
    assert database.runs[message.processing_run_id].status is ProcessingRunStatus.DEAD_LETTERED
    assert database.imports[message.import_id].status is ImportStatus.QUEUED
