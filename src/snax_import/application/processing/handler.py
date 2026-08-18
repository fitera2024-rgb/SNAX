from __future__ import annotations

from snax_import.domain.errors import DigestMismatch, ObjectStorageError, ProcessorNotConfigured
from snax_import.domain.ports import (
    ProcessingContext,
    ProcessingHandlerPort,
    ProcessingOutcome,
    ProcessingOutcomeStatus,
)


class SourceIntegrityTestProcessor(ProcessingHandlerPort):
    """Local/test-only proof of queue lifecycle; it never parses workbook content."""

    def process(self, context: ProcessingContext) -> ProcessingOutcome:
        try:
            if not context.storage.exists(context.source_file.object_key):
                return ProcessingOutcome(
                    ProcessingOutcomeStatus.RETRYABLE_FAILURE,
                    "SOURCE_OBJECT_UNAVAILABLE",
                    "Immutable source object is temporarily unavailable",
                )
            metadata = context.storage.metadata(context.source_file.object_key)
            recorded_size = metadata.get("size")
            if recorded_size is not None and int(recorded_size) != context.source_file.size.value:
                return ProcessingOutcome(
                    ProcessingOutcomeStatus.NONRETRYABLE_FAILURE,
                    "SOURCE_SIZE_MISMATCH",
                    "Immutable source object size does not match PostgreSQL metadata",
                )
            context.storage.verify_digest(
                context.source_file.object_key, context.source_file.sha256
            )
        except DigestMismatch:
            return ProcessingOutcome(
                ProcessingOutcomeStatus.NONRETRYABLE_FAILURE,
                "OBJECT_DIGEST_MISMATCH",
                "Immutable source digest mismatch",
            )
        except (ObjectStorageError, OSError, ValueError):
            return ProcessingOutcome(
                ProcessingOutcomeStatus.RETRYABLE_FAILURE,
                "SOURCE_STORAGE_TEMPORARY_FAILURE",
                "Temporary source storage failure",
            )
        return ProcessingOutcome(
            ProcessingOutcomeStatus.SUCCESS,
            "TECHNICAL_SOURCE_INTEGRITY_TEST_COMPLETED",
            "Technical source integrity test completed; workbook was not parsed",
        )


class DisabledProcessor(ProcessingHandlerPort):
    def process(self, context: ProcessingContext) -> ProcessingOutcome:
        del context
        raise ProcessorNotConfigured()
