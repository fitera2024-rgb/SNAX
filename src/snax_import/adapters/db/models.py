from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from snax_import.adapters.db.base import Base


class SourceFileModel(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_source_files_sha256"),
        CheckConstraint("size_bytes >= 0", name="ck_source_files_size_nonnegative"),
        Index("ix_source_files_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imports: Mapped[list[ImportModel]] = relationship(back_populates="source_file")


class ImportModel(Base):
    __tablename__ = "imports"
    __table_args__ = (
        UniqueConstraint("source_file_id", name="uq_imports_source_file_id"),
        CheckConstraint("version >= 1", name="ck_imports_version_positive"),
        Index("ix_imports_status", "status"),
        Index("ix_imports_created_at", "created_at"),
        Index("ix_imports_source_file_id", "source_file_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    supplier_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_file: Mapped[SourceFileModel] = relationship(back_populates="imports")
    events: Mapped[list[ImportStatusEventModel]] = relationship(
        back_populates="import_record", order_by="ImportStatusEventModel.sequence"
    )
    processing_runs: Mapped[list[ProcessingRunModel]] = relationship(back_populates="import_record")


class ProcessingRunModel(Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        UniqueConstraint("import_id", "run_number", name="uq_processing_runs_import_run"),
        CheckConstraint("run_number >= 1", name="ck_processing_runs_run_number_positive"),
        CheckConstraint("delivery_count >= 0", name="ck_processing_runs_delivery_nonnegative"),
        CheckConstraint("version >= 1", name="ck_processing_runs_version_positive"),
        CheckConstraint(
            "dispatch_generation >= 1", name="ck_processing_runs_dispatch_generation_positive"
        ),
        CheckConstraint(
            "retry_of_run_id IS NULL OR retry_of_run_id <> id",
            name="ck_processing_runs_retry_not_self",
        ),
        CheckConstraint(
            "(started_at IS NULL OR started_at >= queued_at) AND "
            "(heartbeat_at IS NULL OR (started_at IS NOT NULL AND heartbeat_at >= started_at)) AND "
            "(lease_expires_at IS NULL OR (heartbeat_at IS NOT NULL "
            "AND lease_expires_at > heartbeat_at)) AND "
            "(completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)",
            name="ck_processing_runs_timestamp_order",
        ),
        CheckConstraint(
            "(status = 'PROCESSING' AND lease_token IS NOT NULL AND worker_id IS NOT NULL "
            "AND heartbeat_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status <> 'PROCESSING' AND lease_token IS NULL AND worker_id IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_processing_runs_lease_consistency",
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED','TIMED_OUT','DEAD_LETTERED','CANCELLED') "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('QUEUED','PROCESSING') AND completed_at IS NULL)",
            name="ck_processing_runs_completion_consistency",
        ),
        CheckConstraint(
            "(status = 'DEAD_LETTERED' AND dead_lettered_at IS NOT NULL "
            "AND failure_code IS NOT NULL) OR "
            "(status <> 'DEAD_LETTERED' AND dead_lettered_at IS NULL)",
            name="ck_processing_runs_dead_letter_consistency",
        ),
        Index("ix_processing_runs_import_id", "import_id"),
        Index("ix_processing_runs_status", "status"),
        Index("ix_processing_runs_status_lease", "status", "lease_expires_at"),
        Index("ix_processing_runs_status_queued", "status", "queued_at"),
        Index("ix_processing_runs_retry_of", "retry_of_run_id"),
        Index(
            "uq_processing_runs_active_import",
            "import_id",
            unique=True,
            postgresql_where="status IN ('QUEUED', 'PROCESSING')",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    retry_of_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("processing_runs.id", ondelete="RESTRICT"), nullable=True
    )
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    delivery_count: Mapped[int] = mapped_column(nullable=False, default=0)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    failure_retryable: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispatch_generation: Mapped[int] = mapped_column(nullable=False, default=1)
    last_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    import_record: Mapped[ImportModel] = relationship(back_populates="processing_runs")


class OutboxMessageModel(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="ck_outbox_schema_version_positive"),
        CheckConstraint("publish_attempts >= 0", name="ck_outbox_attempts_nonnegative"),
        CheckConstraint("version >= 1", name="ck_outbox_version_positive"),
        CheckConstraint(
            "(status = 'PUBLISHING' AND locked_at IS NOT NULL AND locked_by IS NOT NULL "
            "AND lock_expires_at IS NOT NULL AND lock_expires_at > locked_at) OR "
            "(status <> 'PUBLISHING' AND locked_at IS NULL AND locked_by IS NULL "
            "AND lock_expires_at IS NULL)",
            name="ck_outbox_lock_consistency",
        ),
        CheckConstraint(
            "(status = 'PUBLISHED' AND published_at IS NOT NULL) OR "
            "(status <> 'PUBLISHED' AND published_at IS NULL)",
            name="ck_outbox_published_consistency",
        ),
        Index("ix_outbox_status_available", "status", "available_at"),
        Index("ix_outbox_status_lock_expires", "status", "lock_expires_at"),
        Index("ix_outbox_aggregate_id", "aggregate_id"),
        Index("ix_outbox_processing_run_id", "processing_run_id"),
        Index("ix_outbox_created_at", "created_at"),
        Index("ix_outbox_correlation_id", "correlation_id"),
        Index("ix_outbox_published_at", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    processing_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("processing_runs.id", ondelete="RESTRICT"), nullable=True
    )
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    publish_attempts: Mapped[int] = mapped_column(nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)


class ImportStatusEventModel(Base):
    __tablename__ = "import_status_events"
    __table_args__ = (
        UniqueConstraint("import_id", "sequence", name="uq_import_status_events_import_sequence"),
        CheckConstraint("sequence >= 1", name="ck_import_status_events_sequence_positive"),
        Index("ix_import_status_events_import_id", "import_id"),
        Index("ix_import_status_events_occurred_at", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    import_record: Mapped[ImportModel] = relationship(back_populates="events")
