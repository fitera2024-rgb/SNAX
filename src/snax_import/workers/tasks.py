from __future__ import annotations

from typing import Any

from snax_import.adapters.queue.celery_app import celery_app
from snax_import.workers.worker_runtime import get_worker_runtime


@celery_app.task(  # type: ignore[untyped-decorator]
    name="snax_import.process_import_v1", ignore_result=True
)
def process_import_v1(payload: dict[str, Any]) -> dict[str, object]:
    """Thin transport adapter; lifecycle decisions remain in application services."""

    return get_worker_runtime().handle_payload(payload)
