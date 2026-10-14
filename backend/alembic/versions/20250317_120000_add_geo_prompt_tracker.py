"""Add GEO prompt tracker entries table.

Revision ID: 20250317_120000
Revises: 20250316_120000
Create Date: 2025-03-17 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250317_120000"
down_revision = "20250316_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("geo_prompt_tracker_entries"):
        op.create_table(
            "geo_prompt_tracker_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("context_key", sa.String(), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("citation_hits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "tracked_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
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
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "context_key", "prompt", name="uq_geo_prompt_tracker_user_context_prompt"
            ),
        )

    inspector = sa.inspect(bind)

    indexes = {index["name"] for index in inspector.get_indexes("geo_prompt_tracker_entries")}

    if "ix_geo_prompt_tracker_entries_id" not in indexes:
        op.create_index(
            "ix_geo_prompt_tracker_entries_id", "geo_prompt_tracker_entries", ["id"], unique=False
        )
    if "ix_geo_prompt_tracker_entries_user_id" not in indexes:
        op.create_index(
            "ix_geo_prompt_tracker_entries_user_id",
            "geo_prompt_tracker_entries",
            ["user_id"],
            unique=False,
        )
    if "ix_geo_prompt_tracker_entries_context_key" not in indexes:
        op.create_index(
            "ix_geo_prompt_tracker_entries_context_key",
            "geo_prompt_tracker_entries",
            ["context_key"],
            unique=False,
        )
    if "ix_geo_prompt_tracker_user_context" not in indexes:
        op.create_index(
            "ix_geo_prompt_tracker_user_context",
            "geo_prompt_tracker_entries",
            ["user_id", "context_key"],
            unique=False,
        )
    if "ix_geo_prompt_tracker_context" not in indexes:
        op.create_index(
            "ix_geo_prompt_tracker_context",
            "geo_prompt_tracker_entries",
            ["context_key"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("geo_prompt_tracker_entries"):
        return

    indexes = {index["name"] for index in inspector.get_indexes("geo_prompt_tracker_entries")}
    if "ix_geo_prompt_tracker_context" in indexes:
        op.drop_index("ix_geo_prompt_tracker_context", table_name="geo_prompt_tracker_entries")
    if "ix_geo_prompt_tracker_user_context" in indexes:
        op.drop_index("ix_geo_prompt_tracker_user_context", table_name="geo_prompt_tracker_entries")
    if "ix_geo_prompt_tracker_entries_context_key" in indexes:
        op.drop_index(
            "ix_geo_prompt_tracker_entries_context_key", table_name="geo_prompt_tracker_entries"
        )
    if "ix_geo_prompt_tracker_entries_user_id" in indexes:
        op.drop_index(
            "ix_geo_prompt_tracker_entries_user_id", table_name="geo_prompt_tracker_entries"
        )
    if "ix_geo_prompt_tracker_entries_id" in indexes:
        op.drop_index("ix_geo_prompt_tracker_entries_id", table_name="geo_prompt_tracker_entries")

    op.drop_table("geo_prompt_tracker_entries")
