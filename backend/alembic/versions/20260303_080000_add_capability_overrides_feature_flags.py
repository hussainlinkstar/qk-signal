"""Add workspace_capability_overrides and feature_flags tables

Revision ID: 20260303_080000
Revises: 20260303_070000
Create Date: 2026-03-03 08:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = "20260303_080000"
down_revision = "20260303_070000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_capability_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("capability_key", sa.String(), nullable=False),
        sa.Column("override_value", JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "schema_version",
            sa.String(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_index(
        "ix_wco_workspace_capability",
        "workspace_capability_overrides",
        ["workspace_id", "capability_key"],
        unique=True,
    )

    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("rollout_percentage", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "schema_version",
            sa.String(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wco_workspace_capability",
        table_name="workspace_capability_overrides",
    )
    op.drop_table("feature_flags")
    op.drop_table("workspace_capability_overrides")
