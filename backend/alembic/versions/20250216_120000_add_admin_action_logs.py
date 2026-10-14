"""Add admin_action_logs table.

Revision ID: 20250216_120000
Revises: 20250215_120000
Create Date: 2025-02-16 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250216_120000"
down_revision = "20250215_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("admin_action_logs"):
        op.create_table(
            "admin_action_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "admin_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_admin_action_logs_admin_user_id", "admin_action_logs", ["admin_user_id"]
        )
        op.create_index("ix_admin_action_logs_action", "admin_action_logs", ["action"])
        op.create_index("ix_admin_action_logs_target_type", "admin_action_logs", ["target_type"])
        op.create_index("ix_admin_action_logs_target_id", "admin_action_logs", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_action_logs_target_id", table_name="admin_action_logs", if_exists=True)
    op.drop_index(
        "ix_admin_action_logs_target_type", table_name="admin_action_logs", if_exists=True
    )
    op.drop_index("ix_admin_action_logs_action", table_name="admin_action_logs", if_exists=True)
    op.drop_index(
        "ix_admin_action_logs_admin_user_id", table_name="admin_action_logs", if_exists=True
    )
    op.drop_table("admin_action_logs", if_exists=True)
