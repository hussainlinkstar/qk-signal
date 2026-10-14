"""Add Orchestra V3 signal warehouse tables and snapshot metadata.

Revision ID: 20260316_120000
Revises: 20260311_120000
Create Date: 2026-03-16 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_120000"
down_revision = "20260311_120000"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("signal_audit_snapshots"):
        columns = _column_names(inspector, "signal_audit_snapshots")
        if "pipeline_type" not in columns:
            op.add_column(
                "signal_audit_snapshots", sa.Column("pipeline_type", sa.String(), nullable=True)
            )
        if "agent_count" not in columns:
            op.add_column(
                "signal_audit_snapshots", sa.Column("agent_count", sa.Integer(), nullable=True)
            )
        if "parallel_layers" not in columns:
            op.add_column(
                "signal_audit_snapshots", sa.Column("parallel_layers", sa.Integer(), nullable=True)
            )
        if "total_debate_cost_eur" not in columns:
            op.add_column(
                "signal_audit_snapshots",
                sa.Column("total_debate_cost_eur", sa.Float(), nullable=True),
            )
        if "total_debate_latency_ms" not in columns:
            op.add_column(
                "signal_audit_snapshots",
                sa.Column("total_debate_latency_ms", sa.Integer(), nullable=True),
            )
        if "evidence_anchor" not in columns:
            op.add_column(
                "signal_audit_snapshots",
                sa.Column("evidence_anchor", sa.JSON(), nullable=True),
            )

    if not inspector.has_table("signal_debate_agent_facts"):
        op.create_table(
            "signal_debate_agent_facts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("pipeline_type", sa.String(length=32), nullable=False),
            sa.Column("agent_role", sa.String(length=64), nullable=False),
            sa.Column("agent_layer", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("cost_eur", sa.Float(), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("audit_id", "agent_role", name="uq_signal_debate_agent_audit_role"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("signal_debate_agent_facts"):
        indexes = _index_names(inspector, "signal_debate_agent_facts")
        if "ix_signal_debate_agent_project_date" not in indexes:
            op.create_index(
                "ix_signal_debate_agent_project_date",
                "signal_debate_agent_facts",
                ["project_id", "snapshot_date"],
                unique=False,
            )
        if "ix_signal_debate_agent_provider_date" not in indexes:
            op.create_index(
                "ix_signal_debate_agent_provider_date",
                "signal_debate_agent_facts",
                ["provider", "snapshot_date"],
                unique=False,
            )

    if not inspector.has_table("signal_claim_disposition_facts"):
        op.create_table(
            "signal_claim_disposition_facts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("pipeline_type", sa.String(length=32), nullable=False),
            sa.Column("domain", sa.String(length=16), nullable=False),
            sa.Column("claims_generated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claims_accepted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claims_downgraded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claims_rejected", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "claims_needs_manual_review", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("claims_deduplicated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claims_manually_approved", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claims_manually_refused", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("debate_confidence_score", sa.Float(), nullable=True),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("audit_id", "domain", name="uq_signal_claim_disp_audit_domain"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("signal_claim_disposition_facts"):
        indexes = _index_names(inspector, "signal_claim_disposition_facts")
        if "ix_signal_claim_disp_project_date" not in indexes:
            op.create_index(
                "ix_signal_claim_disp_project_date",
                "signal_claim_disposition_facts",
                ["project_id", "snapshot_date"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("signal_claim_disposition_facts"):
        op.drop_index(
            "ix_signal_claim_disp_project_date",
            table_name="signal_claim_disposition_facts",
            if_exists=True,
        )
        op.drop_table("signal_claim_disposition_facts", if_exists=True)

    if inspector.has_table("signal_debate_agent_facts"):
        op.drop_index(
            "ix_signal_debate_agent_provider_date",
            table_name="signal_debate_agent_facts",
            if_exists=True,
        )
        op.drop_index(
            "ix_signal_debate_agent_project_date",
            table_name="signal_debate_agent_facts",
            if_exists=True,
        )
        op.drop_table("signal_debate_agent_facts", if_exists=True)

    inspector = sa.inspect(bind)
    if inspector.has_table("signal_audit_snapshots"):
        columns = _column_names(inspector, "signal_audit_snapshots")
        if "evidence_anchor" in columns:
            op.drop_column("signal_audit_snapshots", "evidence_anchor")
        if "total_debate_latency_ms" in columns:
            op.drop_column("signal_audit_snapshots", "total_debate_latency_ms")
        if "total_debate_cost_eur" in columns:
            op.drop_column("signal_audit_snapshots", "total_debate_cost_eur")
        if "parallel_layers" in columns:
            op.drop_column("signal_audit_snapshots", "parallel_layers")
        if "agent_count" in columns:
            op.drop_column("signal_audit_snapshots", "agent_count")
        if "pipeline_type" in columns:
            op.drop_column("signal_audit_snapshots", "pipeline_type")
