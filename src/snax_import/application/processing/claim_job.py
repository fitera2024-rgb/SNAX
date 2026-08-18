from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from snax_import.domain.errors import JobNotClaimable, JobNotFound
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.domain.processing import ProcessingRun, ProcessingRunStatus
from snax_import.domain.state_machine import ImportStatus


@dataclass(frozen=True, slots=True)
class ClaimResult:
    claimed: bool
    result: str
    run: ProcessingRun
    lease_token: UUID | None = None


class ClaimJobService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        lease_seconds: int,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.uow_factory = uow_factory
        self.lease_duration = timedelta(seconds=lease_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.token_factory = token_factory

    def claim(self, message: ProcessingJobMessageV1, *, worker_id: str) -> ClaimResult:
        now = self.clock()
        with self.uow_factory() as uow:
            run = uow.processing_runs.by_id(message.processing_run_id, for_update=True)
            if run is None:
                raise JobNotFound()
            aggregate = uow.imports.by_id(message.import_id, for_update=True)
            if aggregate is None:
                raise JobNotFound()
            if (
                run.import_id != message.import_id
                or run.run_number != message.run_number
                or message.dispatch_generation > run.dispatch_generation
            ):
                raise JobNotClaimable("Message does not match durable ProcessingRun")
            if aggregate.status is ImportStatus.CANCELLED:
                if run.status is ProcessingRunStatus.QUEUED:
                    cancelled = run.cancel(now=now)
                    uow.processing_runs.save(cancelled, expected_version=run.version)
                    uow.commit()
                    return ClaimResult(False, "CANCELLED", cancelled)
                return ClaimResult(False, "CANCELLED", run)
            if run.status is not ProcessingRunStatus.QUEUED:
                return ClaimResult(False, "DUPLICATE_DELIVERY", run)
            if aggregate.status is not ImportStatus.QUEUED:
                raise JobNotClaimable(f"Import is {aggregate.status.value}, expected QUEUED")
            lease_token = self.token_factory()
            claimed = run.claim(
                worker_id=worker_id,
                lease_token=lease_token,
                lease_duration=self.lease_duration,
                now=now,
            )
            transition = aggregate.transition(
                ImportStatus.PROCESSING,
                reason="JOB_CLAIMED",
                actor=worker_id,
                now=now,
            )
            uow.processing_runs.save(claimed, expected_version=run.version)
            uow.imports.save_transition(
                transition.aggregate, transition.event, expected_version=aggregate.version
            )
            uow.commit()
            return ClaimResult(True, "CLAIMED", claimed, lease_token)
