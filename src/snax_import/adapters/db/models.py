from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
        Index("ix_processing_runs_import_id", "import_id"),
        Index("ix_processing_runs_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    import_record: Mapped[ImportModel] = relationship(back_populates="processing_runs")


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
