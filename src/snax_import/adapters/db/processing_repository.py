from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from snax_import.adapters.db.models import ProcessingRunModel
from snax_import.domain.errors import PersistenceConflict
from snax_import.domain.processing import ProcessingRun, ProcessingRunStatus


def processing_run_from_model(model: ProcessingRunModel) -> ProcessingRun:
    return ProcessingRun(
        id=model.id,
        import_id=model.import_id,
        run_number=model.run_number,
        status=ProcessingRunStatus(model.status),
        correlation_id=model.correlation_id,
        retry_of_run_id=model.retry_of_run_id,
        queued_at=model.queued_at,
        started_at=model.started_at,
        heartbeat_at=model.heartbeat_at,
        lease_expires_at=model.lease_expires_at,
        completed_at=model.completed_at,
        worker_id=model.worker_id,
        lease_token=model.lease_token,
        delivery_count=model.delivery_count,
        version=model.version,
        failure_code=model.failure_code,
        failure_reason=model.failure_reason,
        failure_retryable=model.failure_retryable,
        dead_lettered_at=model.dead_lettered_at,
        dispatch_generation=model.dispatch_generation,
        last_dispatched_at=model.last_dispatched_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _values(run: ProcessingRun) -> dict[str, object]:
    return {
        "import_id": run.import_id,
        "run_number": run.run_number,
        "status": run.status.value,
        "correlation_id": run.correlation_id,
        "retry_of_run_id": run.retry_of_run_id,
        "queued_at": run.queued_at,
        "started_at": run.started_at,
        "heartbeat_at": run.heartbeat_at,
        "lease_expires_at": run.lease_expires_at,
        "completed_at": run.completed_at,
        "worker_id": run.worker_id,
        "lease_token": run.lease_token,
        "delivery_count": run.delivery_count,
        "version": run.version,
        "failure_code": run.failure_code,
        "failure_reason": run.failure_reason,
        "failure_retryable": run.failure_retryable,
        "dead_lettered_at": run.dead_lettered_at,
        "dispatch_generation": run.dispatch_generation,
        "last_dispatched_at": run.last_dispatched_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


class SqlAlchemyProcessingRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_id(self, run_id: UUID, *, for_update: bool = False) -> ProcessingRun | None:
        query = select(ProcessingRunModel).where(ProcessingRunModel.id == run_id)
        if for_update:
            query = query.with_for_update()
        model = self.session.scalar(query)
        return processing_run_from_model(model) if model is not None else None

    def active_for_import(
        self, import_id: UUID, *, for_update: bool = False
    ) -> ProcessingRun | None:
        query = select(ProcessingRunModel).where(
            ProcessingRunModel.import_id == import_id,
            ProcessingRunModel.status.in_(
                [ProcessingRunStatus.QUEUED.value, ProcessingRunStatus.PROCESSING.value]
            ),
        )
        if for_update:
            query = query.with_for_update()
        model = self.session.scalar(query)
        return processing_run_from_model(model) if model is not None else None

    def latest_for_import(
        self, import_id: UUID, *, for_update: bool = False
    ) -> ProcessingRun | None:
        query = (
            select(ProcessingRunModel)
            .where(ProcessingRunModel.import_id == import_id)
            .order_by(ProcessingRunModel.run_number.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        model = self.session.scalar(query)
        return processing_run_from_model(model) if model is not None else None

    def next_run_number(self, import_id: UUID) -> int:
        current = self.session.scalar(
            select(func.max(ProcessingRunModel.run_number)).where(
                ProcessingRunModel.import_id == import_id
            )
        )
        return int(current or 0) + 1

    def add(self, run: ProcessingRun) -> None:
        self.session.add(ProcessingRunModel(id=run.id, **_values(run)))
        self.session.flush()

    def save(self, run: ProcessingRun, *, expected_version: int) -> None:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(ProcessingRunModel)
                .where(
                    ProcessingRunModel.id == run.id,
                    ProcessingRunModel.version == expected_version,
                )
                .values(**_values(run))
            ),
        )
        if result.rowcount != 1:
            raise PersistenceConflict("ProcessingRun optimistic version conflict")

    def claim_stale_batch(self, *, now: datetime, limit: int) -> Sequence[ProcessingRun]:
        models = self.session.scalars(
            select(ProcessingRunModel)
            .where(
                ProcessingRunModel.status == ProcessingRunStatus.PROCESSING.value,
                ProcessingRunModel.lease_expires_at < now,
            )
            .order_by(ProcessingRunModel.lease_expires_at, ProcessingRunModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        return [processing_run_from_model(model) for model in models]

    def claim_queued_for_redispatch(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[ProcessingRun]:
        models = self.session.scalars(
            select(ProcessingRunModel)
            .where(
                ProcessingRunModel.status == ProcessingRunStatus.QUEUED.value,
                func.coalesce(ProcessingRunModel.last_dispatched_at, ProcessingRunModel.queued_at)
                < older_than,
            )
            .order_by(ProcessingRunModel.queued_at, ProcessingRunModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        return [processing_run_from_model(model) for model in models]

    def list_dead_lettered(self, *, limit: int) -> Sequence[ProcessingRun]:
        models = self.session.scalars(
            select(ProcessingRunModel)
            .where(ProcessingRunModel.status == ProcessingRunStatus.DEAD_LETTERED.value)
            .order_by(ProcessingRunModel.dead_lettered_at.desc())
            .limit(limit)
        ).all()
        return [processing_run_from_model(model) for model in models]
