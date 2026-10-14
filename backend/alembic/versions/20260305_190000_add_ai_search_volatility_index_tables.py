"""Add AI search volatility index tables

Revision ID: 20260305_190000
Revises: 20260305_000000, 20260305_180000
Create Date: 2026-03-05 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_190000"
down_revision = ("20260305_000000", "20260305_180000")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_volatility_seed_queries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("query_text", sa.String(), nullable=False),
        sa.Column("normalized_query", sa.String(), nullable=False),
        sa.Column("industry", sa.String(), nullable=False, server_default="general"),
        sa.Column("priority_weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source", sa.String(), nullable=False, server_default="default_catalog"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "normalized_query",
            "industry",
            name="uq_global_volatility_seed_queries_query_industry",
        ),
    )
    op.create_index(
        "ix_global_volatility_seed_queries_id",
        "global_volatility_seed_queries",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_global_volatility_seed_queries_normalized_query",
        "global_volatility_seed_queries",
        ["normalized_query"],
        unique=False,
    )
    op.create_index(
        "ix_global_volatility_seed_queries_active_industry",
        "global_volatility_seed_queries",
        ["is_active", "industry"],
        unique=False,
    )

    op.create_table(
        "daily_seed_query_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "seed_query_id",
            sa.Integer(),
            sa.ForeignKey("global_volatility_seed_queries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column(
            "visibility_run_batch_id",
            sa.Integer(),
            sa.ForeignKey("visibility_run_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "visibility_run_id",
            sa.Integer(),
            sa.ForeignKey("visibility_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_text_hash", sa.String(), nullable=True),
        sa.Column("citations_hash", sa.String(), nullable=True),
        sa.Column("citation_domains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("citations_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answer_format", sa.String(), nullable=False, server_default="unknown"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "seed_query_id",
            "provider",
            "run_date",
            name="uq_daily_seed_query_runs_seed_provider_date",
        ),
    )
    op.create_index(
        "ix_daily_seed_query_runs_id",
        "daily_seed_query_runs",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_seed_query_id",
        "daily_seed_query_runs",
        ["seed_query_id"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_provider",
        "daily_seed_query_runs",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_run_date",
        "daily_seed_query_runs",
        ["run_date"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_visibility_run_batch_id",
        "daily_seed_query_runs",
        ["visibility_run_batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_visibility_run_id",
        "daily_seed_query_runs",
        ["visibility_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_answer_text_hash",
        "daily_seed_query_runs",
        ["answer_text_hash"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_citations_hash",
        "daily_seed_query_runs",
        ["citations_hash"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_provider_date",
        "daily_seed_query_runs",
        ["provider", "run_date"],
        unique=False,
    )
    op.create_index(
        "ix_daily_seed_query_runs_seed_date",
        "daily_seed_query_runs",
        ["seed_query_id", "run_date"],
        unique=False,
    )

    op.create_table(
        "global_volatility_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("industry", sa.String(), nullable=False, server_default="all"),
        sa.Column("volatility_score", sa.Float(), nullable=True),
        sa.Column("compared_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changed_query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changed_ratio", sa.Float(), nullable=True),
        sa.Column("avg_text_similarity", sa.Float(), nullable=True),
        sa.Column("avg_citation_jaccard", sa.Float(), nullable=True),
        sa.Column("citation_churn_rate", sa.Float(), nullable=True),
        sa.Column("format_change_rate", sa.Float(), nullable=True),
        sa.Column("top_winners", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("top_losers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("changes", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "snapshot_date",
            "provider",
            "industry",
            name="uq_global_volatility_snapshots_date_provider_industry",
        ),
    )
    op.create_index(
        "ix_global_volatility_snapshots_id",
        "global_volatility_snapshots",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_global_volatility_snapshots_snapshot_date",
        "global_volatility_snapshots",
        ["snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_global_volatility_snapshots_provider",
        "global_volatility_snapshots",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_global_volatility_snapshots_industry",
        "global_volatility_snapshots",
        ["industry"],
        unique=False,
    )
    op.create_index(
        "ix_global_volatility_snapshots_provider_date",
        "global_volatility_snapshots",
        ["provider", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_global_volatility_snapshots_industry_date",
        "global_volatility_snapshots",
        ["industry", "snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_global_volatility_snapshots_industry_date", table_name="global_volatility_snapshots"
    )
    op.drop_index(
        "ix_global_volatility_snapshots_provider_date", table_name="global_volatility_snapshots"
    )
    op.drop_index(
        "ix_global_volatility_snapshots_industry", table_name="global_volatility_snapshots"
    )
    op.drop_index(
        "ix_global_volatility_snapshots_provider", table_name="global_volatility_snapshots"
    )
    op.drop_index(
        "ix_global_volatility_snapshots_snapshot_date", table_name="global_volatility_snapshots"
    )
    op.drop_index("ix_global_volatility_snapshots_id", table_name="global_volatility_snapshots")
    op.drop_table("global_volatility_snapshots")

    op.drop_index("ix_daily_seed_query_runs_seed_date", table_name="daily_seed_query_runs")
    op.drop_index("ix_daily_seed_query_runs_provider_date", table_name="daily_seed_query_runs")
    op.drop_index("ix_daily_seed_query_runs_citations_hash", table_name="daily_seed_query_runs")
    op.drop_index("ix_daily_seed_query_runs_answer_text_hash", table_name="daily_seed_query_runs")
    op.drop_index("ix_daily_seed_query_runs_visibility_run_id", table_name="daily_seed_query_runs")
    op.drop_index(
        "ix_daily_seed_query_runs_visibility_run_batch_id", table_name="daily_seed_query_runs"
    )
    op.drop_index("ix_daily_seed_query_runs_run_date", table_name="daily_seed_query_runs")
    op.drop_index("ix_daily_seed_query_runs_provider", table_name="daily_seed_query_runs")
    op.drop_index("ix_daily_seed_query_runs_seed_query_id", table_name="daily_seed_query_runs")
    op.drop_index("ix_daily_seed_query_runs_id", table_name="daily_seed_query_runs")
    op.drop_table("daily_seed_query_runs")

    op.drop_index(
        "ix_global_volatility_seed_queries_active_industry",
        table_name="global_volatility_seed_queries",
    )
    op.drop_index(
        "ix_global_volatility_seed_queries_normalized_query",
        table_name="global_volatility_seed_queries",
    )
    op.drop_index(
        "ix_global_volatility_seed_queries_id", table_name="global_volatility_seed_queries"
    )
    op.drop_table("global_volatility_seed_queries")
