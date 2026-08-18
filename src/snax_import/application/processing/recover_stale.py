from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from snax_import.application.scheduling.schedule_import import enqueue_import
from snax_import.domain.jobs import (
    PROCESSING_EVENT_TYPE,
    PROCESSING_QUEUE,
    build_processing_message,
)
from snax_import.domain.outbox import OutboxMessage
from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.domain.processing import ProcessingRunStatus
from snax_import.domain.retry import RetryPolicy
from snax_import.domain.state_machine import ImportStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    timed_out: int = 0
    retries: int = 0
    dead_lettered: int = 0


class RecoverStaleJobsService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        retry_policy: RetryPolicy,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.retry_policy = retry_policy
        self.clock = clock or (lambda: datetime.now(UTC))

    def recover_once(self, *, limit: int) -> RecoveryResult:
        now = self.clock()
        timed_out = retries = dead_lettered = 0
        with self.uow_factory() as uow:
            for run in uow.processing_runs.claim_stale_batch(now=now, limit=limit):
                if (
                    run.status is not ProcessingRunStatus.PROCESSING
                    or run.lease_expires_at is None
                    or run.lease_expires_at >= now
                ):
                    continue
                aggregate = uow.imports.by_id(run.import_id, for_update=True)
                if aggregate is None or aggregate.status is not ImportStatus.PROCESSING:
                    continue
                expired = run.timeout(
                    code="JOB_HEARTBEAT_EXPIRED",
                    reason="Processing lease expired without heartbeat",
                    now=now,
                )
                transition = aggregate.transition(
                    ImportStatus.FAILED,
                    reason="JOB_HEARTBEAT_EXPIRED",
                    actor="recovery-sweeper",
                    now=now,
                )
                uow.processing_runs.save(expired, expected_version=run.version)
                uow.imports.save_transition(
                    transition.aggregate, transition.event, expected_version=aggregate.version
                )
                timed_out += 1
                logger.warning(
                    "JOB_HEARTBEAT_EXPIRED",
                    extra={
                        "import_id": str(run.import_id),
                        "processing_run_id": str(run.id),
                        "run_number": run.run_number,
                        "correlation_id": run.correlation_id,
                        "retryable": True,
                    },
                )
                if run.run_number < self.retry_policy.max_attempts:
                    delay = self.retry_policy.delay_seconds(run.run_number)
                    enqueue_import(
                        uow=uow,
                        aggregate=transition.aggregate,
                        reason="JOB_RETRY_SCHEDULED:JOB_HEARTBEAT_EXPIRED",
                        actor="recovery-sweeper",
                        now=now,
                        retry_of_run_id=run.id,
                        available_at=now + timedelta(seconds=delay),
                    )
                    retries += 1
                else:
                    dead = expired.dead_letter(
                        code="RETRY_BUDGET_EXHAUSTED",
                        reason="Processing lease expired and retry budget is exhausted",
                        retryable=True,
                        now=now,
                    )
                    uow.processing_runs.save(dead, expected_version=expired.version)
                    dead_lettered += 1
                    logger.error(
                        "JOB_DEAD_LETTERED",
                        extra={
                            "import_id": str(run.import_id),
                            "processing_run_id": str(run.id),
                            "run_number": run.run_number,
                            "correlation_id": run.correlation_id,
                            "result": "RETRY_BUDGET_EXHAUSTED",
                            "retryable": True,
                        },
                    )
            uow.commit()
        return RecoveryResult(timed_out, retries, dead_lettered)


class RedispatchQueuedJobsService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        redelivery_after_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.redelivery_after = timedelta(seconds=redelivery_after_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))

    def redispatch_once(self, *, limit: int) -> int:
        now = self.clock()
        count = 0
        with self.uow_factory() as uow:
            runs = uow.processing_runs.claim_queued_for_redispatch(
                older_than=now - self.redelivery_after, limit=limit
            )
            for run in runs:
                aggregate = uow.imports.by_id(run.import_id, for_update=True)
                if aggregate is None or aggregate.status is not ImportStatus.QUEUED:
                    continue
                redispatched = run.redispatch(now=now)
                message_id = uuid4()
                message = build_processing_message(
                    message_id=message_id,
                    import_id=run.import_id,
                    processing_run_id=run.id,
                    run_number=run.run_number,
                    dispatch_generation=redispatched.dispatch_generation,
                    correlation_id=run.correlation_id,
                    requested_at=now,
                    retry_of_run_id=run.retry_of_run_id,
                )
                outbox = OutboxMessage.create(
                    message_id=message_id,
                    event_type=PROCESSING_EVENT_TYPE,
                    topic=PROCESSING_QUEUE,
                    aggregate_type="Import",
                    aggregate_id=run.import_id,
                    processing_run_id=run.id,
                    correlation_id=run.correlation_id,
                    deduplication_key=(f"process:{run.id}:{redispatched.dispatch_generation}"),
                    payload=message.to_payload(),
                    now=now,
                )
                uow.processing_runs.save(redispatched, expected_version=run.version)
                uow.outbox.add(outbox)
                count += 1
                logger.warning(
                    "JOB_REDISPATCHED",
                    extra={
                        "import_id": str(run.import_id),
                        "processing_run_id": str(run.id),
                        "outbox_message_id": str(outbox.id),
                        "run_number": run.run_number,
                        "dispatch_generation": redispatched.dispatch_generation,
                        "correlation_id": run.correlation_id,
                    },
                )
            uow.commit()
        return count
