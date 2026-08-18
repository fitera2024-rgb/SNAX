from __future__ import annotations

import random
import time
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from snax_import.adapters.db.models import ImportModel, OutboxMessageModel, ProcessingRunModel
from snax_import.adapters.queue.celery_app import celery_app
from snax_import.application.import_registration import UploadRequest
from snax_import.application.processing.claim_job import ClaimJobService
from snax_import.application.processing.complete_job import CompleteJobService
from snax_import.application.processing.heartbeat import HeartbeatJobService
from snax_import.application.processing.recover_stale import (
    RecoverStaleJobsService,
    RedispatchQueuedJobsService,
)
from snax_import.application.scheduling.retry_import import ManualRetryCommand, RetryImportService
from snax_import.application.scheduling.schedule_import import ScheduledImport, enqueue_import
from snax_import.config import settings
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.retry import RetryPolicy
from snax_import.runtime import Runtime, build_runtime


def _policy() -> RetryPolicy:
    return RetryPolicy(
        max_attempts=3,
        base_seconds=1,
        max_seconds=5,
        multiplier=2,
        jitter_ratio=0,
        random_value=random.Random(0).random,
    )


def _register(runtime: Runtime, label: str, payload: bytes) -> UUID:
    marker = uuid4().hex
    result = runtime.service.register(
        UploadRequest(
            stream=BytesIO(payload),
            original_filename="synthetic.bin",
            media_type="application/octet-stream",
            idempotency_key=f"resilience-{label}-{marker}",
            correlation_id=f"resilience-{label}-{marker}",
        )
    )
    return result.import_id


def _schedule(runtime: Runtime, import_id: UUID, *, delay_seconds: float = 0) -> ScheduledImport:
    with runtime.uow_factory() as uow:
        aggregate = uow.imports.by_id(import_id, for_update=True)
        if aggregate is None:
            raise RuntimeError("import disappeared before scheduling")
        now = aggregate.updated_at
        result = enqueue_import(
            uow=uow,
            aggregate=aggregate,
            reason="RESILIENCE_TEST",
            actor="queue-resilience-test",
            now=now,
            available_at=now + timedelta(seconds=delay_seconds),
        )
        uow.commit()
        return result


def _wait_import(runtime: Runtime, import_id: UUID, status: str, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    latest = "missing"
    while time.monotonic() < deadline:
        with runtime.uow_factory() as uow:
            aggregate = uow.imports.by_id(import_id)
        latest = aggregate.status.value if aggregate else "missing"
        if latest == status:
            return
        time.sleep(0.5)
    raise TimeoutError(f"import {import_id} expected {status}, got {latest}")


def _message_for(runtime: Runtime, scheduled: ScheduledImport) -> ProcessingJobMessageV1:
    with runtime.uow_factory() as uow:
        outbox = uow.outbox.by_id(scheduled.outbox.id)
    if outbox is None:
        raise RuntimeError("outbox message disappeared")
    return ProcessingJobMessageV1.from_payload(outbox.payload)


def retry_dead_letter_and_manual_recovery(runtime: Runtime) -> None:
    payload = b"synthetic retry and manual recovery"
    import_id = _register(runtime, "retry", payload)
    scheduled = _schedule(runtime, import_id, delay_seconds=2)
    source = runtime.service.get(import_id)
    if source is None:
        raise RuntimeError("source metadata is missing")
    runtime.storage.delete(source[1].object_key)
    _wait_import(runtime, import_id, "FAILED", timeout=45)
    if runtime.database_engine is None:
        raise RuntimeError("resilience test requires PostgreSQL")
    with Session(runtime.database_engine) as session:
        runs = session.scalars(
            select(ProcessingRunModel)
            .where(ProcessingRunModel.import_id == import_id)
            .order_by(ProcessingRunModel.run_number)
        ).all()
    if len(runs) != 3 or runs[-1].status != "DEAD_LETTERED":
        raise RuntimeError("retry budget did not end in durable dead-letter")
    source_file = source[1]
    runtime.storage.put_stream(
        BytesIO(payload),
        object_key=source_file.object_key,
        digest=source_file.sha256,
        size=source_file.size.value,
        media_type=source_file.media_type.value,
        metadata={"media-type": source_file.media_type.value},
    )
    RetryImportService(runtime.uow_factory).retry(
        ManualRetryCommand(
            import_id=import_id,
            actor="queue-resilience-test",
            reason="restore synthetic object",
            correlation_id=f"manual-retry-{scheduled.run.id}",
        )
    )
    _wait_import(runtime, import_id, "READY_FOR_REVIEW")


def heartbeat_and_stale_recovery(runtime: Runtime) -> None:
    heartbeat_id = _register(runtime, "heartbeat", b"synthetic heartbeat")
    heartbeat_run = _schedule(runtime, heartbeat_id, delay_seconds=120)
    heartbeat_message = _message_for(runtime, heartbeat_run)
    claim = ClaimJobService(
        uow_factory=runtime.uow_factory,
        lease_seconds=3,
        clock=lambda: heartbeat_run.run.queued_at,
    ).claim(heartbeat_message, worker_id="resilience-heartbeat")
    if claim.lease_token is None:
        raise RuntimeError("heartbeat scenario did not claim")
    HeartbeatJobService(
        uow_factory=runtime.uow_factory,
        lease_seconds=3,
        clock=lambda: heartbeat_run.run.queued_at + timedelta(seconds=1),
    ).heartbeat(
        processing_run_id=heartbeat_run.run.id,
        lease_token=claim.lease_token,
        worker_id="resilience-heartbeat",
    )
    recovered = RecoverStaleJobsService(
        uow_factory=runtime.uow_factory,
        retry_policy=_policy(),
        clock=lambda: heartbeat_run.run.queued_at + timedelta(seconds=2),
    ).recover_once(limit=10)
    if recovered.timed_out != 0:
        raise RuntimeError("sweeper recovered a live heartbeating run")
    CompleteJobService(
        uow_factory=runtime.uow_factory,
        clock=lambda: heartbeat_run.run.queued_at + timedelta(seconds=2),
    ).complete(
        processing_run_id=heartbeat_run.run.id,
        lease_token=claim.lease_token,
        worker_id="resilience-heartbeat",
        reason="RESILIENCE_HEARTBEAT_COMPLETED",
    )

    stale_id = _register(runtime, "stale", b"synthetic stale lease")
    stale_run = _schedule(runtime, stale_id, delay_seconds=120)
    stale_message = _message_for(runtime, stale_run)
    ClaimJobService(
        uow_factory=runtime.uow_factory,
        lease_seconds=1,
        clock=lambda: stale_run.run.queued_at,
    ).claim(stale_message, worker_id="resilience-stale")
    stale = RecoverStaleJobsService(
        uow_factory=runtime.uow_factory,
        retry_policy=_policy(),
        clock=lambda: stale_run.run.queued_at + timedelta(seconds=2),
    ).recover_once(limit=10)
    if stale.timed_out != 1 or stale.retries != 1:
        raise RuntimeError("stale lease did not produce exactly one retry")
    _wait_import(runtime, stale_id, "READY_FOR_REVIEW")


def unsupported_schema_and_redispatch(runtime: Runtime) -> None:
    invalid_id = _register(runtime, "schema", b"synthetic unsupported schema")
    invalid = _schedule(runtime, invalid_id, delay_seconds=120)
    with runtime.uow_factory() as uow:
        durable = uow.outbox.by_id(invalid.outbox.id, for_update=True)
        if durable is None:
            raise RuntimeError("invalid-schema outbox is missing")
        dead = durable.mark_dead(
            owner=None,
            code="CONTROLLED_INVALID_DELIVERY",
            message="replaced by controlled broker delivery",
            now=invalid.run.queued_at,
        )
        uow.outbox.save(dead, expected_version=durable.version)
        uow.commit()
    payload = invalid.outbox.payload | {"schemaVersion": 999}
    celery_app.send_task(
        "snax_import.process_import_v1",
        args=[payload],
        task_id=str(uuid4()),
        queue=settings.queue_name,
    )
    _wait_import(runtime, invalid_id, "FAILED")
    with runtime.uow_factory() as uow:
        run = uow.processing_runs.by_id(invalid.run.id)
    if run is None or run.status.value != "DEAD_LETTERED":
        raise RuntimeError("unsupported schema did not become durable dead-letter")

    lost_id = _register(runtime, "redispatch", b"synthetic lost broker message")
    with runtime.uow_factory() as uow:
        aggregate = uow.imports.by_id(lost_id, for_update=True)
        if aggregate is None:
            raise RuntimeError("redispatch import is missing")
        scheduled = enqueue_import(
            uow=uow,
            aggregate=aggregate,
            reason="RESILIENCE_REDISPATCH",
            actor="queue-resilience-test",
            now=aggregate.updated_at,
        )
        claimed = scheduled.outbox.claim(
            owner="simulated-crash-dispatcher",
            now=scheduled.outbox.available_at,
            lock_seconds=30,
        )
        published = claimed.mark_published(
            owner="simulated-crash-dispatcher", now=scheduled.outbox.available_at
        )
        dispatched = scheduled.run.mark_dispatched(now=scheduled.outbox.available_at)
        uow.outbox.save(claimed, expected_version=scheduled.outbox.version)
        uow.outbox.save(published, expected_version=claimed.version)
        uow.processing_runs.save(dispatched, expected_version=scheduled.run.version)
        uow.commit()
    count = RedispatchQueuedJobsService(
        uow_factory=runtime.uow_factory,
        redelivery_after_seconds=1,
        clock=lambda: scheduled.run.queued_at + timedelta(seconds=2),
    ).redispatch_once(limit=10)
    if count != 1:
        raise RuntimeError("lost broker message was not redispatched")
    _wait_import(runtime, lost_id, "READY_FOR_REVIEW")
    if runtime.database_engine is None:
        raise RuntimeError("resilience test requires PostgreSQL")
    with Session(runtime.database_engine) as session:
        run_count = session.scalar(
            select(func.count())
            .select_from(ProcessingRunModel)
            .where(ProcessingRunModel.import_id == lost_id)
        )
        outbox_count = session.scalar(
            select(func.count())
            .select_from(OutboxMessageModel)
            .where(OutboxMessageModel.aggregate_id == lost_id)
        )
        aggregate = session.get(ImportModel, lost_id)
    if run_count != 1 or outbox_count != 2 or aggregate is None:
        raise RuntimeError("redispatch changed logical run cardinality")


def main() -> int:
    runtime = build_runtime(settings)
    retry_dead_letter_and_manual_recovery(runtime)
    heartbeat_and_stale_recovery(runtime)
    unsupported_schema_and_redispatch(runtime)
    print("queue resilience ok: retry/dead-letter/heartbeat/stale/schema/redispatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
