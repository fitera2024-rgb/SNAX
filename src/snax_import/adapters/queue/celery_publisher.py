from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]
from kombu.exceptions import OperationalError  # type: ignore[import-untyped]

from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.ports import ProcessingQueuePort, PublishResult, PublishStatus


class CeleryProcessingQueue(ProcessingQueuePort):
    def __init__(self, application: Celery, *, queue_name: str) -> None:
        self.application = application
        self.queue_name = queue_name

    def publish(self, message: ProcessingJobMessageV1) -> PublishResult:
        try:
            self.application.send_task(
                "snax_import.process_import_v1",
                args=[message.to_payload()],
                task_id=str(message.message_id),
                queue=self.queue_name,
                serializer="json",
                headers={"correlation_id": message.correlation_id},
                ignore_result=True,
            )
        except OperationalError as exc:
            return PublishResult(
                PublishStatus.RETRYABLE_FAILURE,
                error_code="BROKER_UNAVAILABLE",
                error_message=str(exc),
            )
        except (TypeError, ValueError) as exc:
            return PublishResult(
                PublishStatus.NONRETRYABLE_FAILURE,
                error_code="BROKER_MESSAGE_INVALID",
                error_message=str(exc),
            )
        return PublishResult(PublishStatus.ACCEPTED)
