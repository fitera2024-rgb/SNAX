from __future__ import annotations

import json

from snax_import.config import settings
from snax_import.runtime import build_runtime


def main() -> None:
    statuses = build_runtime(settings).readiness(
        redis_url=settings.queue_broker_url or settings.redis_url
    )
    print(json.dumps(statuses))
    if any(value.startswith("error:") for value in statuses.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
