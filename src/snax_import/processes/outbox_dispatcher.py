from __future__ import annotations

import logging
import signal
import socket
from threading import Event

from snax_import.adapters.queue.celery_app import celery_app
from snax_import.adapters.queue.celery_publisher import CeleryProcessingQueue
from snax_import.application.outbox.publish_messages import OutboxDispatcherService
from snax_import.config import settings
from snax_import.logging_config import setup_logging
from snax_import.runtime import build_runtime


def main() -> None:
    setup_logging(settings.log_level)
    stop = Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    runtime = build_runtime(settings)
    dispatcher_id = f"{socket.gethostname()}-{settings.worker_id}-dispatcher"
    service = OutboxDispatcherService(
        uow_factory=runtime.uow_factory,
        queue=CeleryProcessingQueue(celery_app, queue_name=settings.queue_name),
        dispatcher_id=dispatcher_id,
        batch_size=settings.outbox_batch_size,
        lock_seconds=settings.outbox_lock_seconds,
        max_publish_attempts=settings.outbox_max_publish_attempts,
        retry_base_seconds=settings.outbox_retry_base_seconds,
        retry_max_seconds=settings.outbox_retry_max_seconds,
    )
    logger = logging.getLogger(__name__)
    while not stop.is_set():
        try:
            service.dispatch_once()
        except Exception as exc:
            logger.exception("OUTBOX_DISPATCH_CYCLE_FAILED", exc_info=exc)
        stop.wait(settings.outbox_poll_interval_seconds)


if __name__ == "__main__":
    main()
