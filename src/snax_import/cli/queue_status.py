from __future__ import annotations

import argparse
import json

from snax_import.config import settings
from snax_import.runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect durable processing queue state")
    parser.add_argument("--dead-letter", action="store_true", required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    runtime = build_runtime(settings)
    with runtime.uow_factory() as uow:
        runs = uow.processing_runs.list_dead_lettered(limit=args.limit)
    print(
        json.dumps(
            [
                {
                    "processingRunId": str(run.id),
                    "importId": str(run.import_id),
                    "runNumber": run.run_number,
                    "retryOfRunId": str(run.retry_of_run_id) if run.retry_of_run_id else None,
                    "correlationId": run.correlation_id,
                    "failureCode": run.failure_code,
                    "failureReason": run.failure_reason,
                    "failureRetryable": run.failure_retryable,
                    "completedAt": run.completed_at.isoformat() if run.completed_at else None,
                    "deadLetteredAt": (
                        run.dead_lettered_at.isoformat() if run.dead_lettered_at else None
                    ),
                }
                for run in runs
            ]
        )
    )


if __name__ == "__main__":
    main()
