"""queue, transactional outbox and worker

Revision ID: 20260818_0002
Revises: 20260818_0001
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260818_0002"
down_revision: str | None = "20260818_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("processing_runs", sa.Column("correlation_id", sa.String(100)))
    op.add_column("processing_runs", sa.Column("retry_of_run_id", sa.Uuid()))
    op.add_column("processing_runs", sa.Column("queued_at", sa.DateTime(timezone=True)))
    op.add_column("processing_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("processing_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("processing_runs", sa.Column("worker_id", sa.String(200)))
    op.add_column("processing_runs", sa.Column("lease_token", sa.Uuid()))
    op.add_column(
        "processing_runs",
        sa.Column("delivery_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "processing_runs", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("processing_runs", sa.Column("failure_retryable", sa.Boolean()))
    op.add_column("processing_runs", sa.Column("dead_lettered_at", sa.DateTime(timezone=True)))
    op.add_column(
        "processing_runs",
        sa.Column("dispatch_generation", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("processing_runs", sa.Column("last_dispatched_at", sa.DateTime(timezone=True)))
    op.add_column("processing_runs", sa.Column("created_at", sa.DateTime(timezone=True)))
    op.add_column("processing_runs", sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.execute(
        """
        UPDATE processing_runs AS pr
        SET correlation_id = i.correlation_id,
            queued_at = COALESCE(pr.started_at, i.created_at),
            created_at = COALESCE(pr.started_at, i.created_at),
            updated_at = COALESCE(pr.completed_at, pr.started_at, i.updated_at)
        FROM imports AS i
        WHERE i.id = pr.import_id
        """
    )
    op.alter_column("processing_runs", "correlation_id", nullable=False)
    op.alter_column("processing_runs", "queued_at", nullable=False)
    op.alter_column("processing_runs", "created_at", nullable=False)
    op.alter_column("processing_runs", "updated_at", nullable=False)
    op.create_foreign_key(
        "fk_processing_runs_retry_of",
        "processing_runs",
        "processing_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_processing_runs_run_number_positive", "processing_runs", "run_number >= 1"
    )
    op.create_check_constraint(
        "ck_processing_runs_delivery_nonnegative", "processing_runs", "delivery_count >= 0"
    )
    op.create_check_constraint(
        "ck_processing_runs_version_positive", "processing_runs", "version >= 1"
    )
    op.create_check_constraint(
        "ck_processing_runs_dispatch_generation_positive",
        "processing_runs",
        "dispatch_generation >= 1",
    )
    op.create_check_constraint(
        "ck_processing_runs_retry_not_self",
        "processing_runs",
        "retry_of_run_id IS NULL OR retry_of_run_id <> id",
    )
    op.create_check_constraint(
        "ck_processing_runs_timestamp_order",
        "processing_runs",
        "(started_at IS NULL OR started_at >= queued_at) AND "
        "(heartbeat_at IS NULL OR (started_at IS NOT NULL AND heartbeat_at >= started_at)) AND "
        "(lease_expires_at IS NULL OR (heartbeat_at IS NOT NULL "
        "AND lease_expires_at > heartbeat_at)) AND "
        "(completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)",
    )
    op.create_check_constraint(
        "ck_processing_runs_lease_consistency",
        "processing_runs",
        "(status = 'PROCESSING' AND lease_token IS NOT NULL AND worker_id IS NOT NULL "
        "AND heartbeat_at IS NOT NULL AND lease_expires_at IS NOT NULL "
        "AND completed_at IS NULL) OR "
        "(status <> 'PROCESSING' AND lease_token IS NULL AND worker_id IS NULL "
        "AND lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_processing_runs_completion_consistency",
        "processing_runs",
        "(status IN ('SUCCEEDED','FAILED','TIMED_OUT','DEAD_LETTERED','CANCELLED') "
        "AND completed_at IS NOT NULL) OR "
        "(status IN ('QUEUED','PROCESSING') AND completed_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_processing_runs_dead_letter_consistency",
        "processing_runs",
        "(status = 'DEAD_LETTERED' AND dead_lettered_at IS NOT NULL "
        "AND failure_code IS NOT NULL) OR "
        "(status <> 'DEAD_LETTERED' AND dead_lettered_at IS NULL)",
    )
    op.create_index(
        "ix_processing_runs_status_lease", "processing_runs", ["status", "lease_expires_at"]
    )
    op.create_index("ix_processing_runs_status_queued", "processing_runs", ["status", "queued_at"])
    op.create_index("ix_processing_runs_retry_of", "processing_runs", ["retry_of_run_id"])
    op.create_index(
        "uq_processing_runs_active_import",
        "processing_runs",
        ["import_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'PROCESSING')"),
    )

    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid()),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("deduplication_key", sa.String(300), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("last_error_message", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_outbox_payload_object"),
        sa.CheckConstraint("schema_version >= 1", name="ck_outbox_schema_version_positive"),
        sa.CheckConstraint("publish_attempts >= 0", name="ck_outbox_attempts_nonnegative"),
        sa.CheckConstraint("version >= 1", name="ck_outbox_version_positive"),
        sa.CheckConstraint(
            "(status = 'PUBLISHING' AND locked_at IS NOT NULL AND locked_by IS NOT NULL "
            "AND lock_expires_at IS NOT NULL AND lock_expires_at > locked_at) OR "
            "(status <> 'PUBLISHING' AND locked_at IS NULL AND locked_by IS NULL "
            "AND lock_expires_at IS NULL)",
            name="ck_outbox_lock_consistency",
        ),
        sa.CheckConstraint(
            "(status = 'PUBLISHED' AND published_at IS NOT NULL) OR "
            "(status <> 'PUBLISHED' AND published_at IS NULL)",
            name="ck_outbox_published_consistency",
        ),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_key"),
    )
    op.create_index("ix_outbox_status_available", "outbox_messages", ["status", "available_at"])
    op.create_index(
        "ix_outbox_status_lock_expires", "outbox_messages", ["status", "lock_expires_at"]
    )
    for name, column in (
        ("ix_outbox_aggregate_id", "aggregate_id"),
        ("ix_outbox_processing_run_id", "processing_run_id"),
        ("ix_outbox_created_at", "created_at"),
        ("ix_outbox_correlation_id", "correlation_id"),
        ("ix_outbox_published_at", "published_at"),
    ):
        op.create_index(name, "outbox_messages", [column])


def downgrade() -> None:
    for name in (
        "ix_outbox_published_at",
        "ix_outbox_correlation_id",
        "ix_outbox_created_at",
        "ix_outbox_processing_run_id",
        "ix_outbox_aggregate_id",
        "ix_outbox_status_lock_expires",
        "ix_outbox_status_available",
    ):
        op.drop_index(name, table_name="outbox_messages")
    op.drop_table("outbox_messages")
    for name in (
        "uq_processing_runs_active_import",
        "ix_processing_runs_retry_of",
        "ix_processing_runs_status_queued",
        "ix_processing_runs_status_lease",
    ):
        op.drop_index(name, table_name="processing_runs")
    for name in (
        "ck_processing_runs_dead_letter_consistency",
        "ck_processing_runs_completion_consistency",
        "ck_processing_runs_lease_consistency",
        "ck_processing_runs_timestamp_order",
        "ck_processing_runs_retry_not_self",
        "ck_processing_runs_dispatch_generation_positive",
        "ck_processing_runs_version_positive",
        "ck_processing_runs_delivery_nonnegative",
        "ck_processing_runs_run_number_positive",
    ):
        op.drop_constraint(name, "processing_runs", type_="check")
    op.drop_constraint("fk_processing_runs_retry_of", "processing_runs", type_="foreignkey")
    for column in (
        "updated_at",
        "created_at",
        "last_dispatched_at",
        "dispatch_generation",
        "dead_lettered_at",
        "failure_retryable",
        "version",
        "delivery_count",
        "lease_token",
        "worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "queued_at",
        "retry_of_run_id",
        "correlation_id",
    ):
        op.drop_column("processing_runs", column)
