from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_SAFE_EXTRA_FIELDS = (
    "process_name",
    "event_code",
    "import_id",
    "processing_run_id",
    "outbox_message_id",
    "message_id",
    "run_number",
    "dispatch_generation",
    "correlation_id",
    "worker_id",
    "result",
    "duration_ms",
    "retryable",
    "next_attempt_at",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "service": "snax-order-import",
            "event_code": record.getMessage(),
        }
        for field in _SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        handlers=[logging.StreamHandler()],
    )
    logger = logging.getLogger()
    logger.handlers = []
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
