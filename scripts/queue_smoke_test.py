from __future__ import annotations

import os
import time
from uuid import UUID, uuid4

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from snax_import.adapters.db.models import (
    ImportModel,
    ImportStatusEventModel,
    OutboxMessageModel,
    ProcessingRunModel,
    SourceFileModel,
)
from snax_import.adapters.db.session import create_database_engine
from snax_import.adapters.queue.celery_app import celery_app
from snax_import.config import settings


def _wait_for_ready(api_url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    latest = "no response"
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{api_url}/health/ready", timeout=3)
            if response.status_code == 200:
                return
            latest = f"HTTP {response.status_code}: {response.text[:200]}"
        except requests.RequestException as exc:
            latest = str(exc)
        time.sleep(1)
    raise TimeoutError(f"API readiness timed out: {latest}")


def _wait_for_status(api_url: str, import_id: str, timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = requests.get(f"{api_url}/imports/{import_id}", timeout=3)
        response.raise_for_status()
        latest = response.json()
        if latest.get("status") == "READY_FOR_REVIEW":
            return latest
        if latest.get("status") in {"FAILED", "CANCELLED"}:
            raise RuntimeError(f"queue pipeline ended in {latest.get('status')}")
        time.sleep(0.5)
    raise TimeoutError(f"import {import_id} did not complete: {latest}")


def main() -> int:
    api_url = os.environ.get("SMOKE_API_URL", "http://localhost:8000").rstrip("/")
    database_url = os.environ.get(
        "SMOKE_DATABASE_URL",
        "postgresql+psycopg://snax:snax@localhost:5432/snax",
    )
    marker = uuid4().hex
    correlation_id = f"queue-smoke-{marker}"
    _wait_for_ready(api_url, timeout=60)
    response = requests.post(
        f"{api_url}/imports",
        headers={
            "X-Idempotency-Key": f"queue-smoke-{marker}",
            "X-Correlation-ID": correlation_id,
        },
        files={
            "file": ("synthetic.bin", b"synthetic queue smoke payload", "application/octet-stream")
        },
        timeout=10,
    )
    response.raise_for_status()
    if response.status_code != 202:
        raise RuntimeError(f"expected 202, got {response.status_code}")
    import_id = UUID(str(response.json()["importId"]))
    final = _wait_for_status(api_url, str(import_id), timeout=60)
    if final.get("summary", {}).get("correlationId") != correlation_id:  # type: ignore[union-attr]
        raise RuntimeError("correlation ID was not preserved")

    engine = create_database_engine(database_url)
    with Session(engine) as session:
        aggregate = session.get(ImportModel, import_id)
        if aggregate is None or aggregate.status != "READY_FOR_REVIEW":
            raise RuntimeError("durable import status is not READY_FOR_REVIEW")
        source_count = session.scalar(
            select(func.count())
            .select_from(SourceFileModel)
            .where(SourceFileModel.id == aggregate.source_file_id)
        )
        runs = session.scalars(
            select(ProcessingRunModel).where(ProcessingRunModel.import_id == import_id)
        ).all()
        outbox = session.scalars(
            select(OutboxMessageModel).where(OutboxMessageModel.aggregate_id == import_id)
        ).all()
        events = session.scalars(
            select(ImportStatusEventModel)
            .where(ImportStatusEventModel.import_id == import_id)
            .order_by(ImportStatusEventModel.sequence)
        ).all()
        if source_count != 1 or len(runs) != 1 or len(outbox) != 1:
            raise RuntimeError("expected one source, one run and one logical outbox command")
        run = runs[0]
        if run.status != "SUCCEEDED" or outbox[0].status != "PUBLISHED":
            raise RuntimeError("run/outbox durable states are incomplete")
        statuses = [event.new_status for event in events]
        for expected in ("QUEUED", "PROCESSING", "READY_FOR_REVIEW"):
            if statuses.count(expected) != 1:
                raise RuntimeError(f"expected exactly one {expected} lifecycle event")
        duplicate_payload = dict(outbox[0].payload)

    celery_app.send_task(
        "snax_import.process_import_v1",
        args=[duplicate_payload],
        queue=settings.queue_name,
    )
    time.sleep(3)
    with Session(engine) as session:
        run_count = session.scalar(
            select(func.count())
            .select_from(ProcessingRunModel)
            .where(ProcessingRunModel.import_id == import_id)
        )
        completion_count = session.scalar(
            select(func.count())
            .select_from(ImportStatusEventModel)
            .where(
                ImportStatusEventModel.import_id == import_id,
                ImportStatusEventModel.new_status == "READY_FOR_REVIEW",
            )
        )
        if run_count != 1 or completion_count != 1:
            raise RuntimeError("duplicate delivery produced a second durable effect")
    print(f"queue smoke ok: import={import_id}, duplicate delivery was a no-op")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
