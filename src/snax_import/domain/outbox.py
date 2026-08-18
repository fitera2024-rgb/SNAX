from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from snax_import.domain.errors import (
    InvalidValue,
    OutboxLeaseLost,
    OutboxMessageNotClaimable,
)


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    DEAD = "DEAD"


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: UUID
    event_type: str
    topic: str
    schema_version: int
    aggregate_type: str
    aggregate_id: UUID
    processing_run_id: UUID | None
    correlation_id: str
    deduplication_key: str
    payload: dict[str, object]
    status: OutboxStatus
    occurred_at: datetime
    available_at: datetime
    publish_attempts: int
    locked_at: datetime | None
    locked_by: str | None
    lock_expires_at: datetime | None
    published_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    version: int

    def __post_init__(self) -> None:
        for field, timestamp in (
            ("occurredAt", self.occurred_at),
            ("availableAt", self.available_at),
            ("lockedAt", self.locked_at),
            ("lockExpiresAt", self.lock_expires_at),
            ("publishedAt", self.published_at),
            ("createdAt", self.created_at),
            ("updatedAt", self.updated_at),
        ):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0)
            ):
                raise InvalidValue(field, "Timestamp должен быть timezone-aware UTC")
        if self.schema_version < 1 or self.version < 1:
            raise InvalidValue("schemaVersion", "Версии должны быть положительными")
        if self.publish_attempts < 0:
            raise InvalidValue("publishAttempts", "Число попыток не может быть отрицательным")
        if not isinstance(self.payload, dict):
            raise InvalidValue("payload", "Payload должен быть JSON object")
        for field, text, maximum in (
            ("eventType", self.event_type, 100),
            ("topic", self.topic, 200),
            ("aggregateType", self.aggregate_type, 100),
            ("correlationId", self.correlation_id, 100),
            ("deduplicationKey", self.deduplication_key, 300),
        ):
            if not text or len(text) > maximum:
                raise InvalidValue(field, f"Значение должно содержать 1-{maximum} символов")
        locked = (self.locked_at, self.locked_by, self.lock_expires_at)
        if self.status is OutboxStatus.PUBLISHING:
            if any(value is None for value in locked):
                raise InvalidValue("lockedAt", "PUBLISHING требует полный lock")
            assert self.locked_at is not None and self.lock_expires_at is not None
            if self.lock_expires_at <= self.locked_at:
                raise InvalidValue("lockExpiresAt", "Lock expiry должен быть позже lock time")
        elif any(value is not None for value in locked):
            raise InvalidValue("lockedAt", "Lock существует только у PUBLISHING")
        if self.status is OutboxStatus.PUBLISHED and self.published_at is None:
            raise InvalidValue("publishedAt", "PUBLISHED требует timestamp")
        if self.status is not OutboxStatus.PUBLISHED and self.published_at is not None:
            raise InvalidValue("publishedAt", "publishedAt допустим только для PUBLISHED")

    @classmethod
    def create(
        cls,
        *,
        message_id: UUID | None = None,
        event_type: str,
        topic: str,
        aggregate_type: str,
        aggregate_id: UUID,
        processing_run_id: UUID | None,
        correlation_id: str,
        deduplication_key: str,
        payload: dict[str, object],
        available_at: datetime | None = None,
        now: datetime | None = None,
    ) -> OutboxMessage:
        timestamp = now or datetime.now(UTC)
        return cls(
            id=message_id or uuid4(),
            event_type=event_type,
            topic=topic,
            schema_version=1,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            processing_run_id=processing_run_id,
            correlation_id=correlation_id,
            deduplication_key=deduplication_key,
            payload=dict(payload),
            status=OutboxStatus.PENDING,
            occurred_at=timestamp,
            available_at=available_at or timestamp,
            publish_attempts=0,
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            published_at=None,
            last_error_code=None,
            last_error_message=None,
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )

    @property
    def terminal(self) -> bool:
        return self.status in {OutboxStatus.PUBLISHED, OutboxStatus.DEAD}

    def claim(self, *, owner: str, now: datetime, lock_seconds: int) -> OutboxMessage:
        if self.status is not OutboxStatus.PENDING or self.available_at > now:
            raise OutboxMessageNotClaimable()
        if not owner or lock_seconds <= 0:
            raise InvalidValue("lockedBy", "Owner и положительный lock обязательны")
        return replace(
            self,
            status=OutboxStatus.PUBLISHING,
            publish_attempts=self.publish_attempts + 1,
            locked_at=now,
            locked_by=owner,
            lock_expires_at=now + timedelta(seconds=lock_seconds),
            updated_at=now,
            version=self.version + 1,
        )

    def mark_published(self, *, owner: str, now: datetime) -> OutboxMessage:
        self._require_owner(owner, now)
        return replace(
            self,
            status=OutboxStatus.PUBLISHED,
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            published_at=now,
            last_error_code=None,
            last_error_message=None,
            updated_at=now,
            version=self.version + 1,
        )

    def release(
        self,
        *,
        owner: str,
        code: str,
        message: str,
        available_at: datetime,
        now: datetime,
    ) -> OutboxMessage:
        self._require_owner(owner, now)
        return replace(
            self,
            status=OutboxStatus.PENDING,
            available_at=available_at,
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            last_error_code=code,
            last_error_message=message[:2000],
            updated_at=now,
            version=self.version + 1,
        )

    def recover_expired(self, *, now: datetime) -> OutboxMessage:
        if (
            self.status is not OutboxStatus.PUBLISHING
            or self.lock_expires_at is None
            or self.lock_expires_at > now
        ):
            raise OutboxMessageNotClaimable()
        return replace(
            self,
            status=OutboxStatus.PENDING,
            available_at=now,
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            last_error_code="OUTBOX_LOCK_EXPIRED",
            last_error_message="Dispatcher lock expired",
            updated_at=now,
            version=self.version + 1,
        )

    def mark_dead(
        self, *, owner: str | None, code: str, message: str, now: datetime
    ) -> OutboxMessage:
        if self.terminal:
            raise OutboxMessageNotClaimable()
        if self.status is OutboxStatus.PUBLISHING:
            if owner is None:
                raise OutboxLeaseLost()
            self._require_owner(owner, now)
        return replace(
            self,
            status=OutboxStatus.DEAD,
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            last_error_code=code,
            last_error_message=message[:2000],
            updated_at=now,
            version=self.version + 1,
        )

    def _require_owner(self, owner: str, now: datetime) -> None:
        if (
            self.status is not OutboxStatus.PUBLISHING
            or self.locked_by != owner
            or self.lock_expires_at is None
            or self.lock_expires_at <= now
        ):
            raise OutboxLeaseLost()
