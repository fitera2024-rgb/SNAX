from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from snax_import.application.processing.claim_job import ClaimJobService
from snax_import.config import settings
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.ports import UnitOfWorkFactory
from snax_import.runtime import build_runtime


class WorkerRuntime:
    def __init__(self) -> None:
        runtime = build_runtime(settings)
        self.claim_service = ClaimJobService(
            uow_factory=cast(UnitOfWorkFactory, runtime.uow_factory),
            lease_seconds=settings.job_lease_seconds,
        )

    def handle_payload(self, payload: dict[str, Any]) -> dict[str, object]:
        message = ProcessingJobMessageV1.from_payload(payload)
        result = self.claim_service.claim(message, worker_id=settings.worker_id)
        return {
            "claimed": result.claimed,
            "result": result.result,
            "processingRunId": str(result.run.id),
        }


@lru_cache(maxsize=1)
def get_worker_runtime() -> WorkerRuntime:
    return WorkerRuntime()
