from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from snax_import.domain.entities import Import
from snax_import.domain.errors import JobNotClaimable, JobNotFound
from snax_import.domain.jobs import (
    PROCESSING_EVENT_TYPE,
    PROCESSING_QUEUE,
    build_processing_message,
)
from snax_import.domain.outbox import OutboxMessage
from snax_import.domain.ports import UnitOfWorkFactory, UnitOfWorkPort
from snax_import.domain.processing import ProcessingRun
from snax_import.domain.state_machine import ImportStatus


@dataclass(frozen=True, slots=True)
class ScheduledImport:
    aggregate: Import
    run: ProcessingRun
    outbox: OutboxMessage


def enqueue_import(
    *,
    uow: UnitOfWorkPort,
    aggregate: Import,
    reason: str,
    actor: str,
    now: datetime,
    retry_of_run_id: UUID | None = None,
    available_at: datetime | None = None,
    deduplication_key: str | None = None,
) -> ScheduledImport:
    if aggregate.status not in {ImportStatus.STORED, ImportStatus.FAILED}:
        raise JobNotClaimable(f"Import {aggregate.id} is {aggregate.status}")
    if uow.processing_runs.active_for_import(aggregate.id, for_update=True) is not None:
        raise JobNotClaimable("Active processing run already exists")
    run = ProcessingRun.create(
        aggregate.id,
        uow.processing_runs.next_run_number(aggregate.id),
        correlation_id=aggregate.correlation_id.value,
        retry_of_run_id=retry_of_run_id,
        now=now,
    )
    transition = aggregate.transition(
        ImportStatus.QUEUED,
        reason=reason,
        actor=actor,
        correlation_id=aggregate.correlation_id,
        now=now,
    )
    message_id = uuid4()
    message = build_processing_message(
        message_id=message_id,
        import_id=aggregate.id,
        processing_run_id=run.id,
        run_number=run.run_number,
        dispatch_generation=run.dispatch_generation,
        correlation_id=aggregate.correlation_id.value,
        requested_at=now,
        retry_of_run_id=retry_of_run_id,
    )
    outbox = OutboxMessage.create(
        message_id=message_id,
        event_type=PROCESSING_EVENT_TYPE,
        topic=PROCESSING_QUEUE,
        aggregate_type="Import",
        aggregate_id=aggregate.id,
        processing_run_id=run.id,
        correlation_id=aggregate.correlation_id.value,
        deduplication_key=deduplication_key or f"process:{run.id}:{run.dispatch_generation}",
        payload=message.to_payload(),
        available_at=available_at or now,
        now=now,
    )
    uow.imports.save_transition(transition.aggregate, transition.event, aggregate.version)
    uow.processing_runs.add(run)
    uow.outbox.add(outbox)
    return ScheduledImport(transition.aggregate, run, outbox)


class ScheduleImportService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory

    def schedule(self, import_id: UUID, *, actor: str = "scheduler") -> ScheduledImport:
        now = datetime.now(UTC)
        with self.uow_factory() as uow:
            aggregate = uow.imports.by_id(import_id, for_update=True)
            if aggregate is None:
                raise JobNotFound()
            active = uow.processing_runs.active_for_import(import_id, for_update=True)
            if active is not None:
                existing = uow.outbox.by_deduplication_key(
                    f"process:{active.id}:{active.dispatch_generation}"
                )
                if existing is None:
                    raise JobNotClaimable("Active run has no outbox message")
                return ScheduledImport(aggregate, active, existing)
            result = enqueue_import(
                uow=uow,
                aggregate=aggregate,
                reason="Import поставлен в очередь",
                actor=actor,
                now=now,
            )
            uow.commit()
            return result

    def schedule_stored_batch(self, *, limit: int) -> list[ScheduledImport]:
        now = datetime.now(UTC)
        with self.uow_factory() as uow:
            results = [
                enqueue_import(
                    uow=uow,
                    aggregate=aggregate,
                    reason="Stored import поставлен в очередь maintenance scheduler",
                    actor="stored-import-scheduler",
                    now=now,
                )
                for aggregate in uow.imports.claim_stored_batch(limit=limit)
                if uow.processing_runs.active_for_import(aggregate.id, for_update=True) is None
            ]
            uow.commit()
            return results
