from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from snax_import.domain.errors import (
    InvalidValue,
    JobAlreadyClaimed,
    JobAlreadyCompleted,
    JobLeaseLost,
    JobNotClaimable,
)


def _utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise InvalidValue(field, "Timestamp должен быть timezone-aware UTC")


class ProcessingRunStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    DEAD_LETTERED = "DEAD_LETTERED"
    CANCELLED = "CANCELLED"


_COMPLETED = frozenset(
    {
        ProcessingRunStatus.SUCCEEDED,
        ProcessingRunStatus.FAILED,
        ProcessingRunStatus.TIMED_OUT,
        ProcessingRunStatus.DEAD_LETTERED,
        ProcessingRunStatus.CANCELLED,
    }
)
_TERMINAL = frozenset(
    {
        ProcessingRunStatus.SUCCEEDED,
        ProcessingRunStatus.DEAD_LETTERED,
        ProcessingRunStatus.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    id: UUID
    import_id: UUID
    run_number: int
    status: ProcessingRunStatus
    correlation_id: str
    retry_of_run_id: UUID | None
    queued_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    completed_at: datetime | None
    worker_id: str | None
    lease_token: UUID | None
    delivery_count: int
    version: int
    failure_code: str | None
    failure_reason: str | None
    failure_retryable: bool | None
    dead_lettered_at: datetime | None
    dispatch_generation: int
    last_dispatched_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.run_number < 1:
            raise InvalidValue("runNumber", "Номер запуска должен быть положительным")
        if self.delivery_count < 0:
            raise InvalidValue("deliveryCount", "Число доставок не может быть отрицательным")
        if self.version < 1:
            raise InvalidValue("version", "Версия должна быть положительной")
        if self.dispatch_generation < 1:
            raise InvalidValue("dispatchGeneration", "Generation должна быть положительной")
        if not self.correlation_id or len(self.correlation_id) > 100:
            raise InvalidValue("correlationId", "Correlation ID должен содержать 1-100 символов")
        if self.retry_of_run_id == self.id:
            raise InvalidValue("retryOfRunId", "Run не может ссылаться на себя")
        for field, value in (
            ("queuedAt", self.queued_at),
            ("startedAt", self.started_at),
            ("heartbeatAt", self.heartbeat_at),
            ("leaseExpiresAt", self.lease_expires_at),
            ("completedAt", self.completed_at),
            ("deadLetteredAt", self.dead_lettered_at),
            ("lastDispatchedAt", self.last_dispatched_at),
            ("createdAt", self.created_at),
            ("updatedAt", self.updated_at),
        ):
            if value is not None:
                _utc(value, field)
        if self.updated_at < self.created_at or self.queued_at < self.created_at:
            raise InvalidValue("updatedAt", "Временная последовательность run нарушена")
        if self.started_at is not None and self.started_at < self.queued_at:
            raise InvalidValue("startedAt", "startedAt не может быть раньше queuedAt")
        if self.heartbeat_at is not None and (
            self.started_at is None or self.heartbeat_at < self.started_at
        ):
            raise InvalidValue("heartbeatAt", "heartbeatAt требует startedAt и не раньше него")
        if self.lease_expires_at is not None and (
            self.heartbeat_at is None or self.lease_expires_at <= self.heartbeat_at
        ):
            raise InvalidValue("leaseExpiresAt", "Lease должен истекать после heartbeat")
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise InvalidValue("completedAt", "completedAt не может быть раньше startedAt")
        if self.status is ProcessingRunStatus.PROCESSING:
            if None in (
                self.started_at,
                self.heartbeat_at,
                self.lease_expires_at,
                self.worker_id,
                self.lease_token,
            ):
                raise InvalidValue("leaseToken", "PROCESSING run требует полный lease")
            if self.completed_at is not None:
                raise InvalidValue("completedAt", "PROCESSING run не может быть завершён")
        elif (
            self.lease_token is not None
            or self.worker_id is not None
            or self.lease_expires_at is not None
        ):
            raise InvalidValue("leaseToken", "Lease существует только у PROCESSING run")
        if self.status in _COMPLETED and self.completed_at is None:
            raise InvalidValue("completedAt", "Завершённый run требует completedAt")
        if self.status not in _COMPLETED and self.completed_at is not None:
            raise InvalidValue("completedAt", "Незавершённый run не имеет completedAt")
        if self.status is ProcessingRunStatus.DEAD_LETTERED:
            if self.dead_lettered_at is None or self.failure_code is None:
                raise InvalidValue("deadLetteredAt", "Dead-letter требует timestamp и failure code")
        elif self.dead_lettered_at is not None:
            raise InvalidValue("deadLetteredAt", "deadLetteredAt допустим только для dead-letter")

    @classmethod
    def create(
        cls,
        import_id: UUID,
        run_number: int,
        *,
        correlation_id: str = "system",
        retry_of_run_id: UUID | None = None,
        now: datetime | None = None,
    ) -> ProcessingRun:
        timestamp = now or datetime.now(UTC)
        return cls(
            id=uuid4(),
            import_id=import_id,
            run_number=run_number,
            status=ProcessingRunStatus.QUEUED,
            correlation_id=correlation_id,
            retry_of_run_id=retry_of_run_id,
            queued_at=timestamp,
            started_at=None,
            heartbeat_at=None,
            lease_expires_at=None,
            completed_at=None,
            worker_id=None,
            lease_token=None,
            delivery_count=0,
            version=1,
            failure_code=None,
            failure_reason=None,
            failure_retryable=None,
            dead_lettered_at=None,
            dispatch_generation=1,
            last_dispatched_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL

    def claim(
        self,
        *,
        worker_id: str,
        lease_token: UUID,
        lease_duration: timedelta,
        now: datetime,
    ) -> ProcessingRun:
        if self.status is ProcessingRunStatus.PROCESSING:
            raise JobAlreadyClaimed()
        if self.status is not ProcessingRunStatus.QUEUED:
            raise JobNotClaimable()
        if not worker_id.strip() or lease_duration <= timedelta(0):
            raise InvalidValue("workerId", "Worker и положительный lease обязательны")
        _utc(now, "startedAt")
        return replace(
            self,
            status=ProcessingRunStatus.PROCESSING,
            started_at=now,
            heartbeat_at=now,
            lease_expires_at=now + lease_duration,
            worker_id=worker_id,
            lease_token=lease_token,
            delivery_count=self.delivery_count + 1,
            version=self.version + 1,
            updated_at=now,
        )

    def heartbeat(
        self,
        *,
        worker_id: str,
        lease_token: UUID,
        lease_duration: timedelta,
        now: datetime,
    ) -> ProcessingRun:
        self._require_lease(worker_id, lease_token, now, allow_expired=False)
        return replace(
            self,
            heartbeat_at=now,
            lease_expires_at=now + lease_duration,
            version=self.version + 1,
            updated_at=now,
        )

    def succeed(self, *, worker_id: str, lease_token: UUID, now: datetime) -> ProcessingRun:
        self._require_lease(worker_id, lease_token, now, allow_expired=False)
        return self._complete(ProcessingRunStatus.SUCCEEDED, now=now)

    def fail(
        self,
        *,
        worker_id: str,
        lease_token: UUID,
        code: str,
        reason: str,
        retryable: bool,
        now: datetime,
    ) -> ProcessingRun:
        self._require_lease(worker_id, lease_token, now, allow_expired=False)
        return self._complete(
            ProcessingRunStatus.FAILED,
            now=now,
            failure_code=code,
            failure_reason=reason,
            failure_retryable=retryable,
        )

    def timeout(self, *, code: str, reason: str, now: datetime) -> ProcessingRun:
        if self.status is not ProcessingRunStatus.PROCESSING:
            raise JobNotClaimable()
        if self.lease_expires_at is None or self.lease_expires_at > now:
            raise JobNotClaimable("Lease ещё активен")
        return self._complete(
            ProcessingRunStatus.TIMED_OUT,
            now=now,
            failure_code=code,
            failure_reason=reason,
            failure_retryable=True,
        )

    def dead_letter(
        self,
        *,
        code: str,
        reason: str,
        retryable: bool,
        now: datetime,
        worker_id: str | None = None,
        lease_token: UUID | None = None,
    ) -> ProcessingRun:
        if self.terminal:
            raise JobAlreadyCompleted()
        if self.status is ProcessingRunStatus.PROCESSING:
            if worker_id is None or lease_token is None:
                raise JobLeaseLost()
            self._require_lease(worker_id, lease_token, now, allow_expired=False)
        elif self.status not in {
            ProcessingRunStatus.FAILED,
            ProcessingRunStatus.TIMED_OUT,
            ProcessingRunStatus.QUEUED,
        }:
            raise JobNotClaimable()
        started_at = self.started_at or now
        return replace(
            self,
            status=ProcessingRunStatus.DEAD_LETTERED,
            started_at=started_at,
            completed_at=now,
            heartbeat_at=self.heartbeat_at or started_at,
            lease_expires_at=None,
            worker_id=None,
            lease_token=None,
            failure_code=code,
            failure_reason=reason,
            failure_retryable=retryable,
            dead_lettered_at=now,
            version=self.version + 1,
            updated_at=now,
        )

    def cancel(self, *, now: datetime) -> ProcessingRun:
        if self.status is not ProcessingRunStatus.QUEUED:
            raise JobNotClaimable()
        return replace(
            self,
            status=ProcessingRunStatus.CANCELLED,
            started_at=now,
            heartbeat_at=now,
            completed_at=now,
            version=self.version + 1,
            updated_at=now,
        )

    def redispatch(self, *, now: datetime) -> ProcessingRun:
        if self.status is not ProcessingRunStatus.QUEUED:
            raise JobNotClaimable()
        return replace(
            self,
            dispatch_generation=self.dispatch_generation + 1,
            last_dispatched_at=now,
            version=self.version + 1,
            updated_at=now,
        )

    def mark_dispatched(self, *, now: datetime) -> ProcessingRun:
        if self.status is not ProcessingRunStatus.QUEUED:
            return self
        return replace(
            self,
            last_dispatched_at=now,
            version=self.version + 1,
            updated_at=now,
        )

    def _require_lease(
        self, worker_id: str, lease_token: UUID, now: datetime, *, allow_expired: bool
    ) -> None:
        if self.status in _COMPLETED:
            raise JobAlreadyCompleted()
        if self.status is not ProcessingRunStatus.PROCESSING:
            raise JobNotClaimable()
        if self.worker_id != worker_id or self.lease_token != lease_token:
            raise JobLeaseLost()
        if not allow_expired and self.lease_expires_at is not None and self.lease_expires_at <= now:
            raise JobLeaseLost("Lease истёк")

    def _complete(
        self,
        status: ProcessingRunStatus,
        *,
        now: datetime,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        failure_retryable: bool | None = None,
    ) -> ProcessingRun:
        return replace(
            self,
            status=status,
            completed_at=now,
            lease_expires_at=None,
            worker_id=None,
            lease_token=None,
            failure_code=failure_code,
            failure_reason=failure_reason,
            failure_retryable=failure_retryable,
            version=self.version + 1,
            updated_at=now,
        )
