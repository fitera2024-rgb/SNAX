from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from snax_import.application.scheduling.schedule_import import ScheduledImport, enqueue_import
from snax_import.domain.errors import InvalidValue, JobNotClaimable, JobNotFound
from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.domain.state_machine import ImportStatus


@dataclass(frozen=True, slots=True)
class ManualRetryCommand:
    import_id: UUID
    actor: str
    reason: str
    correlation_id: str

    def __post_init__(self) -> None:
        for field, value in (
            ("actor", self.actor),
            ("reason", self.reason),
            ("correlationId", self.correlation_id),
        ):
            if not value.strip():
                raise InvalidValue(field, "Value must not be blank")
        if len(self.actor) > 100 or len(self.correlation_id) > 100:
            raise InvalidValue("manualRetry", "Actor and correlation ID are limited to 100 chars")
        if len(self.reason) > 1000:
            raise InvalidValue("reason", "Reason is limited to 1000 chars")


class RetryImportService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory

    def retry(self, command: ManualRetryCommand) -> ScheduledImport:
        key = f"manual-retry:{command.import_id}:{command.correlation_id}"
        with self.uow_factory() as uow:
            existing = uow.outbox.by_deduplication_key(key)
            if existing is not None and existing.processing_run_id is not None:
                run = uow.processing_runs.by_id(existing.processing_run_id)
                aggregate = uow.imports.by_id(command.import_id)
                if run is None or aggregate is None:
                    raise JobNotFound("Idempotent retry records are incomplete")
                return ScheduledImport(aggregate, run, existing)
            aggregate = uow.imports.by_id(command.import_id, for_update=True)
            if aggregate is None:
                raise JobNotFound()
            # A concurrent command may have committed while this transaction waited
            # for the import row lock. Re-check the durable command key under the lock.
            existing = uow.outbox.by_deduplication_key(key)
            if existing is not None and existing.processing_run_id is not None:
                run = uow.processing_runs.by_id(existing.processing_run_id)
                if run is None:
                    raise JobNotFound("Idempotent retry run is missing")
                return ScheduledImport(aggregate, run, existing)
            if aggregate.status is not ImportStatus.FAILED:
                raise JobNotClaimable("Manual retry is allowed only for FAILED imports")
            active = uow.processing_runs.active_for_import(command.import_id, for_update=True)
            if active is not None:
                raise JobNotClaimable("Active processing run already exists")
            previous = uow.processing_runs.latest_for_import(command.import_id, for_update=True)
            result = enqueue_import(
                uow=uow,
                aggregate=aggregate,
                reason=f"MANUAL_RETRY:{command.reason}",
                actor=command.actor,
                now=datetime.now(UTC),
                retry_of_run_id=previous.id if previous is not None else None,
                deduplication_key=key,
            )
            uow.commit()
            return result
