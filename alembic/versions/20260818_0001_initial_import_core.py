"""initial import core

Revision ID: 20260818_0001
Revises:
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_source_files_sha256"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_source_files_size_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_source_files_created_at", "source_files", ["created_at"])

    op.create_table(
        "imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("supplier_code", sa.String(length=100), nullable=True),
        sa.Column("profile_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_imports_version_positive"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("source_file_id", name="uq_imports_source_file_id"),
    )
    op.create_index("ix_imports_status", "imports", ["status"])
    op.create_index("ix_imports_created_at", "imports", ["created_at"])
    op.create_index("ix_imports_source_file_id", "imports", ["source_file_id"])

    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("failure_reason", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "run_number", name="uq_processing_runs_import_run"),
    )
    op.create_index("ix_processing_runs_import_id", "processing_runs", ["import_id"])
    op.create_index("ix_processing_runs_status", "processing_runs", ["status"])

    op.create_table(
        "import_status_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_import_status_events_sequence_positive"),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_id", "sequence", name="uq_import_status_events_import_sequence"
        ),
    )
    op.create_index("ix_import_status_events_import_id", "import_status_events", ["import_id"])
    op.create_index("ix_import_status_events_occurred_at", "import_status_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_import_status_events_occurred_at", table_name="import_status_events")
    op.drop_index("ix_import_status_events_import_id", table_name="import_status_events")
    op.drop_table("import_status_events")
    op.drop_index("ix_processing_runs_status", table_name="processing_runs")
    op.drop_index("ix_processing_runs_import_id", table_name="processing_runs")
    op.drop_table("processing_runs")
    op.drop_index("ix_imports_source_file_id", table_name="imports")
    op.drop_index("ix_imports_created_at", table_name="imports")
    op.drop_index("ix_imports_status", table_name="imports")
    op.drop_table("imports")
    op.drop_index("ix_source_files_created_at", table_name="source_files")
    op.drop_table("source_files")
