from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from snax_import.application.scheduling.schedule_import import ScheduledImport, enqueue_import
from snax_import.domain.errors import JobAlreadyCompleted, JobNotClaimable, JobNotFound
from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.domain.processing import ProcessingRun
from snax_import.domain.retry import RetryPolicy
from snax_import.domain.state_machine import ImportStatus


@dataclass(frozen=True, slots=True)
class FailureResult:
    run: ProcessingRun
    retry: ScheduledImport | None
    dead_lettered: bool


class FailJobService:
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

    def fail(
        self,
        *,
        processing_run_id: UUID,
        lease_token: UUID,
        worker_id: str,
        code: str,
        reason: str,
        retryable: bool,
    ) -> FailureResult:
        with self.uow_factory() as uow:
            run = uow.processing_runs.by_id(processing_run_id, for_update=True)
            if run is None:
                raise JobNotFound()
            if run.terminal:
                raise JobAlreadyCompleted()
            aggregate = uow.imports.by_id(run.import_id, for_update=True)
            if aggregate is None:
                raise JobNotFound()
            if aggregate.status is not ImportStatus.PROCESSING:
                raise JobNotClaimable("Import is not PROCESSING")
            now = self.clock()
            attempts_remain = retryable and run.run_number < self.retry_policy.max_attempts
            if attempts_remain:
                failed = run.fail(
                    worker_id=worker_id,
                    lease_token=lease_token,
                    code=code,
                    reason=reason,
                    retryable=True,
                    now=now,
                )
            else:
                final_code = code if not retryable else "RETRY_BUDGET_EXHAUSTED"
                failed = run.dead_letter(
                    worker_id=worker_id,
                    lease_token=lease_token,
                    code=final_code,
                    reason=reason,
                    retryable=retryable,
                    now=now,
                )
            transition = aggregate.transition(
                ImportStatus.FAILED,
                reason=failed.failure_code or code,
                actor=worker_id,
                now=now,
            )
            uow.processing_runs.save(failed, expected_version=run.version)
            uow.imports.save_transition(
                transition.aggregate, transition.event, expected_version=aggregate.version
            )
            retry: ScheduledImport | None = None
            if attempts_remain:
                delay = self.retry_policy.delay_seconds(run.run_number)
                retry = enqueue_import(
                    uow=uow,
                    aggregate=transition.aggregate,
                    reason=f"JOB_RETRY_SCHEDULED:{code}",
                    actor="processing-retry",
                    now=now,
                    retry_of_run_id=run.id,
                    available_at=now + timedelta(seconds=delay),
                )
            uow.commit()
            return FailureResult(failed, retry, not attempts_remain)
