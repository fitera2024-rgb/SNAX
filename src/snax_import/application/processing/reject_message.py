from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.domain.processing import ProcessingRunStatus
from snax_import.domain.state_machine import ImportStatus


class RejectInvalidMessageService:
    """Persists a nonretryable result when an invalid delivery identifies a durable run."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory

    def reject(self, payload: Mapping[str, object], *, code: str, reason: str) -> bool:
        try:
            import_id = UUID(str(payload["importId"]))
            run_id = UUID(str(payload["processingRunId"]))
        except (KeyError, TypeError, ValueError):
            return False
        now = datetime.now(UTC)
        worker = "message-validator"
        token = uuid4()
        with self.uow_factory() as uow:
            run = uow.processing_runs.by_id(run_id, for_update=True)
            aggregate = uow.imports.by_id(import_id, for_update=True)
            if run is None or aggregate is None or run.import_id != import_id:
                return False
            if run.terminal or run.status is not ProcessingRunStatus.QUEUED:
                return True
            if aggregate.status is not ImportStatus.QUEUED:
                return False
            claimed = run.claim(
                worker_id=worker,
                lease_token=token,
                lease_duration=timedelta(seconds=30),
                now=now,
            )
            processing = aggregate.transition(
                ImportStatus.PROCESSING,
                reason="JOB_MESSAGE_REJECTED",
                actor=worker,
                now=now,
            )
            dead = claimed.dead_letter(
                code=code,
                reason=reason,
                retryable=False,
                worker_id=worker,
                lease_token=token,
                now=now,
            )
            failed = processing.aggregate.transition(
                ImportStatus.FAILED,
                reason=code,
                actor=worker,
                now=now,
            )
            uow.processing_runs.save(claimed, expected_version=run.version)
            uow.processing_runs.save(dead, expected_version=claimed.version)
            uow.imports.save_transition(
                processing.aggregate, processing.event, expected_version=aggregate.version
            )
            uow.imports.save_transition(
                failed.aggregate,
                failed.event,
                expected_version=processing.aggregate.version,
            )
            uow.commit()
            return True
