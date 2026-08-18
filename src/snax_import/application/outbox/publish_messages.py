from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from snax_import.domain.errors import DomainError
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.outbox import OutboxStatus
from snax_import.domain.ports import (
    ProcessingQueuePort,
    PublishResult,
    PublishStatus,
    UnitOfWorkFactory,
)
from snax_import.domain.processing import ProcessingRunStatus


class OutboxDispatcherService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        queue: ProcessingQueuePort,
        dispatcher_id: str,
        batch_size: int,
        lock_seconds: int,
        max_publish_attempts: int,
        retry_base_seconds: float,
        retry_max_seconds: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.queue = queue
        self.dispatcher_id = dispatcher_id
        self.batch_size = batch_size
        self.lock_seconds = lock_seconds
        self.max_publish_attempts = max_publish_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.logger = logging.getLogger(__name__)

    def dispatch_once(self) -> int:
        now = self.clock()
        with self.uow_factory() as uow:
            recovered = uow.outbox.recover_expired_locks(now=now, limit=self.batch_size)
            claimed = uow.outbox.claim_due_batch(
                now=now,
                owner=self.dispatcher_id,
                lock_seconds=self.lock_seconds,
                limit=self.batch_size,
            )
            uow.commit()
        for item in recovered:
            self.logger.warning(
                "OUTBOX_LOCK_RECOVERED",
                extra={"outbox_message_id": str(item.id), "correlation_id": item.correlation_id},
            )
        for item in claimed:
            self.logger.info(
                "OUTBOX_MESSAGE_CLAIMED",
                extra={
                    "outbox_message_id": str(item.id),
                    "processing_run_id": (
                        str(item.processing_run_id) if item.processing_run_id else None
                    ),
                    "correlation_id": item.correlation_id,
                },
            )
            try:
                message = ProcessingJobMessageV1.from_payload(item.payload)
            except DomainError as exc:
                self._finish(
                    item.id,
                    PublishResult(
                        PublishStatus.NONRETRYABLE_FAILURE,
                        error_code=getattr(exc, "code", "OUTBOX_MESSAGE_INVALID"),
                        error_message=str(exc),
                    ),
                )
                continue
            self._finish(item.id, self.queue.publish(message))
        return len(claimed)

    def _finish(self, message_id: UUID, result: PublishResult) -> None:
        now = self.clock()
        with self.uow_factory() as uow:
            durable = uow.outbox.by_id(message_id, for_update=True)
            if durable is None:
                return
            if result.status is PublishStatus.ACCEPTED:
                updated = durable.mark_published(owner=self.dispatcher_id, now=now)
                if durable.processing_run_id is not None:
                    run = uow.processing_runs.by_id(durable.processing_run_id, for_update=True)
                    if run is not None and run.status is ProcessingRunStatus.QUEUED:
                        dispatched = run.mark_dispatched(now=now)
                        uow.processing_runs.save(dispatched, expected_version=run.version)
            elif (
                result.status is PublishStatus.NONRETRYABLE_FAILURE
                or durable.publish_attempts >= self.max_publish_attempts
            ):
                code = result.error_code or "OUTBOX_PUBLISH_ATTEMPTS_EXHAUSTED"
                updated = durable.mark_dead(
                    owner=self.dispatcher_id,
                    code=code,
                    message=result.error_message or code,
                    now=now,
                )
            else:
                delay = min(
                    self.retry_max_seconds,
                    self.retry_base_seconds * 2 ** max(0, durable.publish_attempts - 1),
                )
                updated = durable.release(
                    owner=self.dispatcher_id,
                    code=result.error_code or "OUTBOX_PUBLISH_FAILED",
                    message=result.error_message or "Broker publish failed",
                    available_at=now + timedelta(seconds=delay),
                    now=now,
                )
            uow.outbox.save(updated, expected_version=durable.version)
            uow.commit()
        event_code = {
            OutboxStatus.PUBLISHED: "OUTBOX_MESSAGE_PUBLISHED",
            OutboxStatus.PENDING: "OUTBOX_PUBLISH_FAILED",
            OutboxStatus.DEAD: "OUTBOX_MESSAGE_DEAD",
        }[updated.status]
        self.logger.info(
            event_code,
            extra={
                "outbox_message_id": str(updated.id),
                "processing_run_id": (
                    str(updated.processing_run_id) if updated.processing_run_id else None
                ),
                "correlation_id": updated.correlation_id,
                "result": updated.status.value,
                "retryable": updated.status is OutboxStatus.PENDING,
                "next_attempt_at": (
                    updated.available_at.isoformat()
                    if updated.status is OutboxStatus.PENDING
                    else None
                ),
            },
        )
