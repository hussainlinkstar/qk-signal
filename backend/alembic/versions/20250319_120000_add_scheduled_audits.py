"""Add scheduled_audits table.

Revision ID: 20250319_120000
Revises: 71a0bcfdd8cc
Create Date: 2025-03-19 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20250319_120000"
down_revision = "71a0bcfdd8cc"
branch_labels = None
depends_on = None


SCHEDULED_FREQUENCY_ENUM = sa.Enum(
    "weekly",
    "monthly",
    name="scheduled_audit_frequency",
    native_enum=False,
)
SCHEDULED_PAUSE_REASON_ENUM = sa.Enum(
    "insufficient_credits",
    "plan_restricted",
    "manual",
    name="scheduled_audit_pause_reason",
    native_enum=False,
)
SCHEDULED_RUN_STATUS_ENUM = sa.Enum(
    "queued",
    "succeeded",
    "failed",
    "paused",
    name="scheduled_audit_run_status",
    native_enum=False,
)
AUDIT_TYPE_ENUM = sa.Enum(
    "FAST",
    "SMART",
    "STANDARD",
    "DEEP",
    name="audit_type",
    native_enum=False,
)


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _check_constraint_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_check_constraints(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("scheduled_audits"):
        op.create_table(
            "scheduled_audits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("site_id", sa.Integer(), nullable=True),
            sa.Column("type", AUDIT_TYPE_ENUM, nullable=False, server_default="STANDARD"),
            sa.Column("url", sa.String(), nullable=False),
            sa.Column(
                "frequency", SCHEDULED_FREQUENCY_ENUM, nullable=False, server_default="weekly"
            ),
            sa.Column("audit_params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paused_reason", SCHEDULED_PAUSE_REASON_ENUM, nullable=True),
            sa.Column("last_run_status", SCHEDULED_RUN_STATUS_ENUM, nullable=True),
            sa.Column("last_job_id", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "(project_id IS NOT NULL) OR (site_id IS NOT NULL)",
                name="ck_scheduled_audits_target",
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        columns = _column_names(inspector, "scheduled_audits")
        if "site_id" not in columns:
            op.add_column(
                "scheduled_audits",
                sa.Column("site_id", sa.Integer(), nullable=True),
            )
            op.create_foreign_key(
                "fk_scheduled_audits_site_id_sites",
                "scheduled_audits",
                "sites",
                ["site_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if "paused_reason" not in columns:
            op.add_column(
                "scheduled_audits",
                sa.Column("paused_reason", SCHEDULED_PAUSE_REASON_ENUM, nullable=True),
            )
        if "last_run_status" not in columns:
            op.add_column(
                "scheduled_audits",
                sa.Column("last_run_status", SCHEDULED_RUN_STATUS_ENUM, nullable=True),
            )
        if "last_job_id" not in columns:
            op.add_column(
                "scheduled_audits",
                sa.Column("last_job_id", sa.String(), nullable=True),
            )

    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "scheduled_audits")
    if "ix_scheduled_audits_id" not in indexes:
        op.create_index("ix_scheduled_audits_id", "scheduled_audits", ["id"], unique=False)
    if "ix_scheduled_audits_user_id" not in indexes:
        op.create_index(
            "ix_scheduled_audits_user_id", "scheduled_audits", ["user_id"], unique=False
        )
    if "ix_scheduled_audits_next_run_at" not in indexes:
        op.create_index(
            "ix_scheduled_audits_next_run_at", "scheduled_audits", ["next_run_at"], unique=False
        )
    if "ix_scheduled_audits_last_job_id" not in indexes:
        op.create_index(
            "ix_scheduled_audits_last_job_id", "scheduled_audits", ["last_job_id"], unique=False
        )
    if "ix_scheduled_audits_project_id" not in indexes:
        op.create_index(
            "ix_scheduled_audits_project_id", "scheduled_audits", ["project_id"], unique=False
        )
    if "ix_scheduled_audits_site_id" not in indexes:
        op.create_index(
            "ix_scheduled_audits_site_id", "scheduled_audits", ["site_id"], unique=False
        )
    if "ix_scheduled_audits_user_id_is_active" not in indexes:
        op.create_index(
            "ix_scheduled_audits_user_id_is_active",
            "scheduled_audits",
            ["user_id", "is_active"],
            unique=False,
        )
    if "ix_scheduled_audits_is_active_next_run" not in indexes:
        op.create_index(
            "ix_scheduled_audits_is_active_next_run",
            "scheduled_audits",
            ["is_active", "next_run_at"],
            unique=False,
        )

    checks = _check_constraint_names(inspector, "scheduled_audits")
    if "ck_scheduled_audits_target" not in checks:
        op.create_check_constraint(
            "ck_scheduled_audits_target",
            "scheduled_audits",
            "(project_id IS NOT NULL) OR (site_id IS NOT NULL)",
        )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduled_audits_is_active_next_run", table_name="scheduled_audits", if_exists=True
    )
    op.drop_index(
        "ix_scheduled_audits_user_id_is_active", table_name="scheduled_audits", if_exists=True
    )
    op.drop_index("ix_scheduled_audits_site_id", table_name="scheduled_audits", if_exists=True)
    op.drop_index("ix_scheduled_audits_project_id", table_name="scheduled_audits", if_exists=True)
    op.drop_index("ix_scheduled_audits_last_job_id", table_name="scheduled_audits", if_exists=True)
    op.drop_index("ix_scheduled_audits_next_run_at", table_name="scheduled_audits", if_exists=True)
    op.drop_index("ix_scheduled_audits_user_id", table_name="scheduled_audits", if_exists=True)
    op.drop_index("ix_scheduled_audits_id", table_name="scheduled_audits", if_exists=True)
    op.drop_table("scheduled_audits", if_exists=True)
