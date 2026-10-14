"""Add debate traces table for admin-only Orchestra debug workflows.

Revision ID: 20260316_170000
Revises: 20260316_143000
Create Date: 2026-03-16 17:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_170000"
down_revision = "20260316_143000"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("debate_traces"):
        op.create_table(
            "debate_traces",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("agent_role", sa.String(length=64), nullable=False),
            sa.Column("agent_layer", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pipeline_type", sa.String(length=32), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=False),
            sa.Column("input_payload_hash", sa.String(length=64), nullable=False),
            sa.Column("input_payload_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("input_summary", sa.Text(), nullable=True),
            sa.Column("input_payload_raw", sa.Text(), nullable=False),
            sa.Column("output_raw", sa.Text(), nullable=False),
            sa.Column("output_claim_ledger", sa.JSON(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_eur", sa.Float(), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("debate_traces"):
        indexes = _index_names(inspector, "debate_traces")
        if "ix_debate_trace_audit_layer" not in indexes:
            op.create_index(
                "ix_debate_trace_audit_layer",
                "debate_traces",
                ["audit_id", "agent_layer"],
                unique=False,
            )
        if "ix_debate_trace_audit_role" not in indexes:
            op.create_index(
                "ix_debate_trace_audit_role",
                "debate_traces",
                ["audit_id", "agent_role"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("debate_traces"):
        op.drop_index("ix_debate_trace_audit_role", table_name="debate_traces", if_exists=True)
        op.drop_index("ix_debate_trace_audit_layer", table_name="debate_traces", if_exists=True)
        op.drop_table("debate_traces", if_exists=True)
