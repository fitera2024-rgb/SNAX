from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from snax_import.adapters.db.models import OutboxMessageModel
from snax_import.domain.errors import PersistenceConflict
from snax_import.domain.outbox import OutboxMessage, OutboxStatus


def outbox_from_model(model: OutboxMessageModel) -> OutboxMessage:
    return OutboxMessage(
        id=model.id,
        event_type=model.event_type,
        topic=model.topic,
        schema_version=model.schema_version,
        aggregate_type=model.aggregate_type,
        aggregate_id=model.aggregate_id,
        processing_run_id=model.processing_run_id,
        correlation_id=model.correlation_id,
        deduplication_key=model.deduplication_key,
        payload=dict(model.payload),
        status=OutboxStatus(model.status),
        occurred_at=model.occurred_at,
        available_at=model.available_at,
        publish_attempts=model.publish_attempts,
        locked_at=model.locked_at,
        locked_by=model.locked_by,
        lock_expires_at=model.lock_expires_at,
        published_at=model.published_at,
        last_error_code=model.last_error_code,
        last_error_message=model.last_error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _values(message: OutboxMessage) -> dict[str, object]:
    return {
        "event_type": message.event_type,
        "topic": message.topic,
        "schema_version": message.schema_version,
        "aggregate_type": message.aggregate_type,
        "aggregate_id": message.aggregate_id,
        "processing_run_id": message.processing_run_id,
        "correlation_id": message.correlation_id,
        "deduplication_key": message.deduplication_key,
        "payload": message.payload,
        "status": message.status.value,
        "occurred_at": message.occurred_at,
        "available_at": message.available_at,
        "publish_attempts": message.publish_attempts,
        "locked_at": message.locked_at,
        "locked_by": message.locked_by,
        "lock_expires_at": message.lock_expires_at,
        "published_at": message.published_at,
        "last_error_code": message.last_error_code,
        "last_error_message": message.last_error_message,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "version": message.version,
    }


def _write_model(model: OutboxMessageModel, message: OutboxMessage) -> None:
    for key, value in _values(message).items():
        setattr(model, key, value)


class SqlAlchemyOutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_id(self, message_id: UUID, *, for_update: bool = False) -> OutboxMessage | None:
        query = select(OutboxMessageModel).where(OutboxMessageModel.id == message_id)
        if for_update:
            query = query.with_for_update()
        model = self.session.scalar(query)
        return outbox_from_model(model) if model is not None else None

    def by_deduplication_key(self, key: str) -> OutboxMessage | None:
        model = self.session.scalar(
            select(OutboxMessageModel).where(OutboxMessageModel.deduplication_key == key)
        )
        return outbox_from_model(model) if model is not None else None

    def add(self, message: OutboxMessage) -> None:
        self.session.add(OutboxMessageModel(id=message.id, **_values(message)))
        self.session.flush()

    def save(self, message: OutboxMessage, *, expected_version: int) -> None:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(OutboxMessageModel)
                .where(
                    OutboxMessageModel.id == message.id,
                    OutboxMessageModel.version == expected_version,
                )
                .values(**_values(message))
            ),
        )
        if result.rowcount != 1:
            raise PersistenceConflict("Outbox optimistic version conflict")

    def claim_due_batch(
        self, *, now: datetime, owner: str, lock_seconds: int, limit: int
    ) -> Sequence[OutboxMessage]:
        models = self.session.scalars(
            select(OutboxMessageModel)
            .where(
                OutboxMessageModel.status == OutboxStatus.PENDING.value,
                OutboxMessageModel.available_at <= now,
            )
            .order_by(OutboxMessageModel.available_at, OutboxMessageModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        claimed: list[OutboxMessage] = []
        for model in models:
            item = outbox_from_model(model).claim(owner=owner, now=now, lock_seconds=lock_seconds)
            _write_model(model, item)
            claimed.append(item)
        self.session.flush()
        return claimed

    def recover_expired_locks(self, *, now: datetime, limit: int) -> Sequence[OutboxMessage]:
        models = self.session.scalars(
            select(OutboxMessageModel)
            .where(
                OutboxMessageModel.status == OutboxStatus.PUBLISHING.value,
                OutboxMessageModel.lock_expires_at <= now,
            )
            .order_by(OutboxMessageModel.lock_expires_at, OutboxMessageModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        recovered: list[OutboxMessage] = []
        for model in models:
            item = outbox_from_model(model).recover_expired(now=now)
            _write_model(model, item)
            recovered.append(item)
        self.session.flush()
        return recovered
