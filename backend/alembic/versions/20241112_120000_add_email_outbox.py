"""Add email outbox table.

Revision ID: 20241112_120000
Revises: 20241105_120000
Create Date: 2024-11-12 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20241112_120000"
down_revision = "20241105_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "email_outbox" not in inspector.get_table_names():
        op.create_table(
            "email_outbox",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("to_email", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("html_body", sa.Text(), nullable=True),
            sa.Column("text_body", sa.Text(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("correlation_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_email_outbox_user_id"),
        )
    inspector = sa.inspect(bind)
    if "email_outbox" not in inspector.get_table_names():
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes("email_outbox")}
    if "ix_email_outbox_user_id" not in existing_indexes:
        op.create_index("ix_email_outbox_user_id", "email_outbox", ["user_id"])
    if "ix_email_outbox_category" not in existing_indexes:
        op.create_index("ix_email_outbox_category", "email_outbox", ["category"])
    if "ix_email_outbox_correlation_id" not in existing_indexes:
        op.create_index("ix_email_outbox_correlation_id", "email_outbox", ["correlation_id"])
    if "ix_email_outbox_status" not in existing_indexes:
        op.create_index("ix_email_outbox_status", "email_outbox", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "email_outbox" not in inspector.get_table_names():
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes("email_outbox")}
    if "ix_email_outbox_status" in existing_indexes:
        op.drop_index("ix_email_outbox_status", table_name="email_outbox")
    if "ix_email_outbox_correlation_id" in existing_indexes:
        op.drop_index("ix_email_outbox_correlation_id", table_name="email_outbox")
    if "ix_email_outbox_category" in existing_indexes:
        op.drop_index("ix_email_outbox_category", table_name="email_outbox")
    if "ix_email_outbox_user_id" in existing_indexes:
        op.drop_index("ix_email_outbox_user_id", table_name="email_outbox")
    op.drop_table("email_outbox")
