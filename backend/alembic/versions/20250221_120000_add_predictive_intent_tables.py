"""add predictive intent tables

Revision ID: 20250221_120000
Revises: 20250220_120000
Create Date: 2025-02-21 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250221_120000"
down_revision: Union[str, None] = "20250220_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intent_corpus_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_intent_corpus_entries_id"), "intent_corpus_entries", ["id"], unique=False
    )
    op.create_index(
        "ix_intent_corpus_entries_created_at", "intent_corpus_entries", ["created_at"], unique=False
    )

    op.create_table(
        "intent_query_telemetry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_intent_query_telemetry_id"), "intent_query_telemetry", ["id"], unique=False
    )
    op.create_index(
        "ix_intent_query_telemetry_created_at",
        "intent_query_telemetry",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_intent_query_telemetry_provider_created",
        "intent_query_telemetry",
        ["provider", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_intent_query_telemetry_provider_created", table_name="intent_query_telemetry")
    op.drop_index("ix_intent_query_telemetry_created_at", table_name="intent_query_telemetry")
    op.drop_index(op.f("ix_intent_query_telemetry_id"), table_name="intent_query_telemetry")
    op.drop_table("intent_query_telemetry")

    op.drop_index("ix_intent_corpus_entries_created_at", table_name="intent_corpus_entries")
    op.drop_index(op.f("ix_intent_corpus_entries_id"), table_name="intent_corpus_entries")
    op.drop_table("intent_corpus_entries")
