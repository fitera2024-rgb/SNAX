from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from snax_import.domain.errors import InvalidValue, JobSchemaUnsupported
from snax_import.domain.value_objects import CorrelationId

PROCESSING_EVENT_TYPE = "IMPORT_PROCESSING_REQUESTED"
PROCESSING_QUEUE = "snax.import.processing.v1"
_FIELDS = {
    "schemaVersion",
    "messageId",
    "eventType",
    "importId",
    "processingRunId",
    "runNumber",
    "dispatchGeneration",
    "correlationId",
    "requestedAt",
    "retryOfRunId",
}
_REQUIRED = _FIELDS - {"retryOfRunId"}


@dataclass(frozen=True, slots=True)
class ProcessingJobMessageV1:
    message_id: UUID
    import_id: UUID
    processing_run_id: UUID
    run_number: int
    dispatch_generation: int
    correlation_id: str
    requested_at: datetime
    retry_of_run_id: UUID | None = None
    schema_version: int = 1
    event_type: str = PROCESSING_EVENT_TYPE

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise JobSchemaUnsupported()
        if self.event_type != PROCESSING_EVENT_TYPE:
            raise InvalidValue("eventType", "Неподдерживаемый event type")
        if self.run_number < 1 or self.dispatch_generation < 1:
            raise InvalidValue("runNumber", "Run number и generation должны быть положительными")
        CorrelationId(self.correlation_id)
        offset = self.requested_at.utcoffset()
        if self.requested_at.tzinfo is None or offset is None:
            raise InvalidValue("requestedAt", "Timestamp должен содержать timezone")
        if offset.total_seconds() != 0:
            raise InvalidValue("requestedAt", "Timestamp должен быть UTC")

    def to_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "messageId": str(self.message_id),
            "eventType": self.event_type,
            "importId": str(self.import_id),
            "processingRunId": str(self.processing_run_id),
            "runNumber": self.run_number,
            "dispatchGeneration": self.dispatch_generation,
            "correlationId": self.correlation_id,
            "requestedAt": self.requested_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "retryOfRunId": str(self.retry_of_run_id) if self.retry_of_run_id else None,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ProcessingJobMessageV1:
        if not isinstance(payload, dict):
            raise InvalidValue("payload", "Message должен быть JSON object")
        unknown = set(payload) - _FIELDS
        missing = _REQUIRED - set(payload)
        if unknown or missing:
            raise InvalidValue("payload", f"Unknown={sorted(unknown)} missing={sorted(missing)}")
        if type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1:
            raise JobSchemaUnsupported()
        for field in (
            "messageId",
            "eventType",
            "importId",
            "processingRunId",
            "correlationId",
            "requestedAt",
        ):
            if type(payload[field]) is not str:
                raise InvalidValue("payload", f"{field} must be a JSON string")
        for field in ("runNumber", "dispatchGeneration"):
            if type(payload[field]) is not int:
                raise InvalidValue("payload", f"{field} must be a JSON integer")
        if payload.get("retryOfRunId") is not None and type(payload["retryOfRunId"]) is not str:
            raise InvalidValue("payload", "retryOfRunId must be a JSON string or null")
        try:
            requested_at = datetime.fromisoformat(
                str(payload["requestedAt"]).replace("Z", "+00:00")
            )
            retry_value = payload.get("retryOfRunId")
            return cls(
                message_id=UUID(str(payload["messageId"])),
                import_id=UUID(str(payload["importId"])),
                processing_run_id=UUID(str(payload["processingRunId"])),
                run_number=int(payload["runNumber"]),
                dispatch_generation=int(payload["dispatchGeneration"]),
                correlation_id=str(payload["correlationId"]),
                requested_at=requested_at,
                retry_of_run_id=UUID(str(retry_value)) if retry_value is not None else None,
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise InvalidValue("payload", "Некорректный ProcessingJobMessageV1") from exc


def build_processing_message(
    *,
    message_id: UUID,
    import_id: UUID,
    processing_run_id: UUID,
    run_number: int,
    dispatch_generation: int,
    correlation_id: str,
    requested_at: datetime,
    retry_of_run_id: UUID | None,
) -> ProcessingJobMessageV1:
    return ProcessingJobMessageV1(
        message_id=message_id,
        import_id=import_id,
        processing_run_id=processing_run_id,
        run_number=run_number,
        dispatch_generation=dispatch_generation,
        correlation_id=correlation_id,
        requested_at=requested_at,
        retry_of_run_id=retry_of_run_id,
    )
