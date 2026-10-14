"""add advisor_chat_messages (persisted multi-turn advisor chat history)

Revision ID: 20260430_090000
Revises: 20260429_090000
Create Date: 2026-04-30 09:00:00

Creates the ``advisor_chat_messages`` table that persists the audit-grounded
Advisor chat transcript so follow-up questions carry prior-turn context. Each
row is one turn (``user`` or ``assistant``) scoped to a single (audit, user)
pair. The assistant turn also stores the validated ``citations`` it was grounded
on. Stored ``content`` is RAW-sanitized (control chars stripped, length-capped)
— never HTML-escaped (React escapes at render).

This is PRIOR-TURN CONTEXT ONLY: history is replayed to the model as delimited
user/assistant data, never merged into the system prompt, so the closed-world /
grounding / abstention guarantees are unchanged.

Nullable-safe / additive only: a new table is created (no DROP, no SET NOT NULL
on an existing populated column, no column rename). Guarded by an inspector
check so re-running is idempotent.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_090000"
down_revision = "20260429_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "advisor_chat_messages" in set(inspector.get_table_names()):
        return

    op.create_table(
        "advisor_chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_advisor_chat_messages_id", "advisor_chat_messages", ["id"], unique=False)
    op.create_index(
        "ix_advisor_chat_messages_audit_id",
        "advisor_chat_messages",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        "ix_advisor_chat_messages_audit_user_created",
        "advisor_chat_messages",
        ["audit_id", "user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "advisor_chat_messages" not in set(inspector.get_table_names()):
        return
    op.drop_index(
        "ix_advisor_chat_messages_audit_user_created",
        table_name="advisor_chat_messages",
    )
    op.drop_index("ix_advisor_chat_messages_audit_id", table_name="advisor_chat_messages")
    op.drop_index("ix_advisor_chat_messages_id", table_name="advisor_chat_messages")
    op.drop_table("advisor_chat_messages")
