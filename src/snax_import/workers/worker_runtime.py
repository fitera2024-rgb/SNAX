from __future__ import annotations

import json
import logging
import random
from functools import lru_cache
from typing import Any

from snax_import.application.processing.claim_job import ClaimJobService
from snax_import.application.processing.complete_job import CompleteJobService
from snax_import.application.processing.fail_job import FailJobService
from snax_import.application.processing.handler import (
    DisabledProcessor,
    SourceIntegrityTestProcessor,
)
from snax_import.application.processing.heartbeat import HeartbeatJobService
from snax_import.application.processing.reject_message import RejectInvalidMessageService
from snax_import.config import settings
from snax_import.domain.errors import DomainError, JobLeaseLost, ProcessorNotConfigured
from snax_import.domain.jobs import ProcessingJobMessageV1
from snax_import.domain.ports import (
    ProcessingContext,
    ProcessingHandlerPort,
    ProcessingOutcome,
    ProcessingOutcomeStatus,
)
from snax_import.domain.retry import RetryPolicy
from snax_import.runtime import build_runtime
from snax_import.workers.heartbeat_runner import HeartbeatRunner


class WorkerRuntime:
    def __init__(self) -> None:
        runtime = build_runtime(settings)
        self.runtime = runtime
        self.logger = logging.getLogger(__name__)
        self.claim_service = ClaimJobService(
            uow_factory=runtime.uow_factory,
            lease_seconds=settings.job_lease_seconds,
        )
        self.heartbeat_service = HeartbeatJobService(
            uow_factory=runtime.uow_factory,
            lease_seconds=settings.job_lease_seconds,
        )
        self.complete_service = CompleteJobService(uow_factory=runtime.uow_factory)
        self.fail_service = FailJobService(
            uow_factory=runtime.uow_factory,
            retry_policy=RetryPolicy(
                max_attempts=settings.processing_max_attempts,
                base_seconds=settings.processing_retry_base_seconds,
                max_seconds=settings.processing_retry_max_seconds,
                multiplier=settings.processing_retry_multiplier,
                jitter_ratio=settings.processing_retry_jitter_ratio,
                random_value=random.SystemRandom().random,
            ),
        )
        self.reject_service = RejectInvalidMessageService(runtime.uow_factory)
        self.handler: ProcessingHandlerPort = self._build_handler()

    def _build_handler(self) -> ProcessingHandlerPort:
        if settings.processor_mode == "source-integrity-test":
            return SourceIntegrityTestProcessor()
        return DisabledProcessor()

    def handle_payload(self, payload: dict[str, Any]) -> dict[str, object]:
        encoded_size = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        if encoded_size > settings.queue_message_max_bytes:
            self.reject_service.reject(
                payload,
                code="JOB_MESSAGE_TOO_LARGE",
                reason="Processing message exceeds configured size limit",
            )
            return {"claimed": False, "result": "JOB_MESSAGE_TOO_LARGE"}
        try:
            message = ProcessingJobMessageV1.from_payload(payload)
        except DomainError as exc:
            code = getattr(exc, "code", "JOB_MESSAGE_INVALID")
            self.reject_service.reject(payload, code=code, reason=str(exc))
            self.logger.warning("JOB_MESSAGE_REJECTED", extra={"result": code})
            return {"claimed": False, "result": code}
        log_context = {
            "import_id": str(message.import_id),
            "processing_run_id": str(message.processing_run_id),
            "message_id": str(message.message_id),
            "run_number": message.run_number,
            "dispatch_generation": message.dispatch_generation,
            "correlation_id": message.correlation_id,
            "worker_id": settings.worker_id,
        }
        self.logger.info("JOB_MESSAGE_RECEIVED", extra=log_context)
        claim = self.claim_service.claim(message, worker_id=settings.worker_id)
        if not claim.claimed or claim.lease_token is None:
            self.logger.info(
                "JOB_DELIVERY_DUPLICATE",
                extra={**log_context, "result": claim.result},
            )
            return {
                "claimed": False,
                "result": claim.result,
                "processingRunId": str(claim.run.id),
            }
        lease_token = claim.lease_token
        self.logger.info("JOB_CLAIMED", extra=log_context)
        with self.runtime.uow_factory() as uow:
            source = uow.imports.source_for_import(message.import_id)
        if source is None:
            outcome = ProcessingOutcome(
                ProcessingOutcomeStatus.NONRETRYABLE_FAILURE,
                "SOURCE_FILE_NOT_FOUND",
                "Source metadata not found",
            )
        else:
            context = ProcessingContext(
                import_id=message.import_id,
                processing_run_id=message.processing_run_id,
                run_number=message.run_number,
                correlation_id=message.correlation_id,
                effect_key=str(message.processing_run_id),
                source_file=source,
                storage=self.runtime.storage,
            )
            runner = HeartbeatRunner(
                interval_seconds=settings.job_heartbeat_seconds,
                heartbeat=lambda: self.heartbeat_service.heartbeat(
                    processing_run_id=message.processing_run_id,
                    lease_token=lease_token,
                    worker_id=settings.worker_id,
                ),
            )
            try:
                with runner:
                    outcome = self.handler.process(context)
                runner.raise_if_failed()
            except JobLeaseLost:
                return {
                    "claimed": True,
                    "result": "JOB_LEASE_LOST",
                    "processingRunId": str(claim.run.id),
                }
            except ProcessorNotConfigured:
                outcome = ProcessingOutcome(
                    ProcessingOutcomeStatus.NONRETRYABLE_FAILURE,
                    "PROCESSOR_NOT_CONFIGURED",
                    "Processing handler is not configured",
                )
            except Exception as exc:
                self.logger.exception(
                    "JOB_PROCESSING_FAILED",
                    exc_info=exc,
                    extra={
                        "import_id": str(message.import_id),
                        "processing_run_id": str(message.processing_run_id),
                        "correlation_id": message.correlation_id,
                        "worker_id": settings.worker_id,
                        "retryable": True,
                    },
                )
                outcome = ProcessingOutcome(
                    ProcessingOutcomeStatus.RETRYABLE_FAILURE,
                    "PROCESSING_INFRASTRUCTURE_FAILURE",
                    "Temporary processing infrastructure failure",
                )

        if outcome.status is ProcessingOutcomeStatus.SUCCESS:
            completion = self.complete_service.complete(
                processing_run_id=message.processing_run_id,
                lease_token=lease_token,
                worker_id=settings.worker_id,
                reason=outcome.code,
            )
            self.logger.info(
                "JOB_COMPLETED",
                extra={**log_context, "result": outcome.code},
            )
            return {
                "claimed": True,
                "result": outcome.code,
                "completed": completion.completed,
                "processingRunId": str(claim.run.id),
            }
        failure = self.fail_service.fail(
            processing_run_id=message.processing_run_id,
            lease_token=lease_token,
            worker_id=settings.worker_id,
            code=outcome.code,
            reason=outcome.reason,
            retryable=outcome.status is ProcessingOutcomeStatus.RETRYABLE_FAILURE,
        )
        event_code = "JOB_DEAD_LETTERED" if failure.dead_lettered else "JOB_RETRY_SCHEDULED"
        self.logger.warning(
            event_code,
            extra={
                **log_context,
                "result": failure.run.failure_code or outcome.code,
                "retryable": outcome.status is ProcessingOutcomeStatus.RETRYABLE_FAILURE,
            },
        )
        return {
            "claimed": True,
            "result": failure.run.failure_code or outcome.code,
            "deadLettered": failure.dead_lettered,
            "retryRunId": str(failure.retry.run.id) if failure.retry else None,
            "processingRunId": str(claim.run.id),
        }


@lru_cache(maxsize=1)
def get_worker_runtime() -> WorkerRuntime:
    return WorkerRuntime()
