from __future__ import annotations

import argparse
import json
from uuid import UUID

from snax_import.application.scheduling.retry_import import ManualRetryCommand, RetryImportService
from snax_import.config import settings
from snax_import.runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry a FAILED import")
    parser.add_argument("--import-id", type=UUID, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--correlation-id", required=True)
    args = parser.parse_args()
    result = RetryImportService(build_runtime(settings).uow_factory).retry(
        ManualRetryCommand(
            import_id=args.import_id,
            actor=args.actor,
            reason=args.reason,
            correlation_id=args.correlation_id,
        )
    )
    print(
        json.dumps(
            {
                "importId": str(result.aggregate.id),
                "processingRunId": str(result.run.id),
                "runNumber": result.run.run_number,
                "outboxMessageId": str(result.outbox.id),
            }
        )
    )


if __name__ == "__main__":
    main()
