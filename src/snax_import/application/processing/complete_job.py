from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from snax_import.domain.errors import JobAlreadyCompleted, JobNotClaimable, JobNotFound
from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.domain.processing import ProcessingRun, ProcessingRunStatus
from snax_import.domain.state_machine import ImportStatus


@dataclass(frozen=True, slots=True)
class CompletionResult:
    completed: bool
    run: ProcessingRun


class CompleteJobService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    def complete(
        self, *, processing_run_id: UUID, lease_token: UUID, worker_id: str, reason: str
    ) -> CompletionResult:
        with self.uow_factory() as uow:
            run = uow.processing_runs.by_id(processing_run_id, for_update=True)
            if run is None:
                raise JobNotFound()
            if run.status is ProcessingRunStatus.SUCCEEDED:
                return CompletionResult(False, run)
            if run.terminal:
                raise JobAlreadyCompleted()
            aggregate = uow.imports.by_id(run.import_id, for_update=True)
            if aggregate is None:
                raise JobNotFound()
            if aggregate.status is not ImportStatus.PROCESSING:
                raise JobNotClaimable("Import is not PROCESSING")
            now = self.clock()
            completed = run.succeed(worker_id=worker_id, lease_token=lease_token, now=now)
            transition = aggregate.transition(
                ImportStatus.READY_FOR_REVIEW,
                reason=reason,
                actor=worker_id,
                now=now,
            )
            uow.processing_runs.save(completed, expected_version=run.version)
            uow.imports.save_transition(
                transition.aggregate, transition.event, expected_version=aggregate.version
            )
            uow.commit()
            return CompletionResult(True, completed)
