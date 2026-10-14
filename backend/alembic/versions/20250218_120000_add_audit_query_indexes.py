"""Add indexes for high-volume audit history lookups.

Revision ID: 20250218_120000
Revises: 20250217_120000
Create Date: 2025-02-18 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250218_120000"
down_revision = "20250217_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("audits"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("audits")}

        if "ix_audits_user_id" not in existing_indexes:
            op.create_index("ix_audits_user_id", "audits", ["user_id"], unique=False)

        if "ix_audits_created_at" not in existing_indexes:
            op.create_index("ix_audits_created_at", "audits", ["created_at"], unique=False)

        if "ix_audits_request_id" not in existing_indexes:
            op.create_index("ix_audits_request_id", "audits", ["request_id"], unique=False)

        if "ix_audits_user_id_created_at" not in existing_indexes:
            op.create_index(
                "ix_audits_user_id_created_at", "audits", ["user_id", "created_at"], unique=False
            )


def downgrade() -> None:
    op.drop_index("ix_audits_user_id_created_at", table_name="audits", if_exists=True)
    op.drop_index("ix_audits_request_id", table_name="audits", if_exists=True)
    op.drop_index("ix_audits_created_at", table_name="audits", if_exists=True)
    op.drop_index("ix_audits_user_id", table_name="audits", if_exists=True)
