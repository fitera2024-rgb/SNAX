from __future__ import annotations

import logging
import random
import signal
from threading import Event

from snax_import.application.processing.recover_stale import (
    RecoverStaleJobsService,
    RedispatchQueuedJobsService,
)
from snax_import.application.scheduling.schedule_import import ScheduleImportService
from snax_import.config import settings
from snax_import.domain.retry import RetryPolicy
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
    retry_policy = RetryPolicy(
        max_attempts=settings.processing_max_attempts,
        base_seconds=settings.processing_retry_base_seconds,
        max_seconds=settings.processing_retry_max_seconds,
        multiplier=settings.processing_retry_multiplier,
        jitter_ratio=settings.processing_retry_jitter_ratio,
        random_value=random.SystemRandom().random,
    )
    recovery = RecoverStaleJobsService(
        uow_factory=runtime.uow_factory,
        retry_policy=retry_policy,
    )
    redispatch = RedispatchQueuedJobsService(
        uow_factory=runtime.uow_factory,
        redelivery_after_seconds=settings.queue_redelivery_after_seconds,
    )
    scheduler = ScheduleImportService(runtime.uow_factory)
    logger = logging.getLogger(__name__)
    while not stop.is_set():
        try:
            if settings.processing_autostart:
                scheduler.schedule_stored_batch(limit=settings.outbox_batch_size)
            result = recovery.recover_once(limit=settings.outbox_batch_size)
            redelivered = redispatch.redispatch_once(limit=settings.outbox_batch_size)
            if result.timed_out or redelivered:
                logger.info(
                    "RECOVERY_CYCLE_COMPLETED",
                    extra={
                        "result": (
                            f"timed_out={result.timed_out},retries={result.retries},"
                            f"dead={result.dead_lettered},redispatched={redelivered}"
                        )
                    },
                )
        except Exception as exc:
            logger.exception("RECOVERY_CYCLE_FAILED", exc_info=exc)
        stop.wait(settings.recovery_poll_interval_seconds)


if __name__ == "__main__":
    main()
