from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from snax_import.config import settings


def create_celery_app() -> Celery:
    broker_url = settings.queue_broker_url or settings.redis_url or "redis://localhost:6379/0"
    application = Celery("snax-import-worker", broker=broker_url, backend=None)
    application.conf.update(
        accept_content=["json"],
        task_serializer="json",
        result_serializer="json",
        task_ignore_result=True,
        result_backend=None,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=settings.worker_prefetch_multiplier,
        broker_connection_retry_on_startup=True,
        enable_utc=True,
        timezone="UTC",
        task_soft_time_limit=settings.worker_soft_time_limit_seconds,
        task_time_limit=settings.worker_hard_time_limit_seconds,
        broker_transport_options={
            "visibility_timeout": settings.queue_visibility_timeout_seconds,
        },
        task_default_queue=settings.queue_name,
        task_routes={"snax_import.process_import_v1": {"queue": settings.queue_name}},
        imports=("snax_import.workers.tasks",),
    )
    return application


celery_app = create_celery_app()
