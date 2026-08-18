from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from snax_import.domain.errors import JobNotFound
from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.domain.processing import ProcessingRun


class HeartbeatJobService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        lease_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.lease_duration = timedelta(seconds=lease_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))

    def heartbeat(
        self, *, processing_run_id: UUID, lease_token: UUID, worker_id: str
    ) -> ProcessingRun:
        with self.uow_factory() as uow:
            run = uow.processing_runs.by_id(processing_run_id, for_update=True)
            if run is None:
                raise JobNotFound()
            updated = run.heartbeat(
                worker_id=worker_id,
                lease_token=lease_token,
                lease_duration=self.lease_duration,
                now=self.clock(),
            )
            uow.processing_runs.save(updated, expected_version=run.version)
            uow.commit()
            return updated
