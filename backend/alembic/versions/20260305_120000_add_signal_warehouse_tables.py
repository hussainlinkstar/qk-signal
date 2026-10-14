"""Add signal warehouse, benchmark, and proprietary score tables

Revision ID: 20260305_120000
Revises: 20260305_010000
Create Date: 2026-03-05 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_120000"
down_revision = "20260305_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_audit_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id",
            sa.Integer(),
            sa.ForeignKey("audits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("score_dimension", sa.String(), nullable=False),
        sa.Column("score_value", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("tier_class", sa.String(), nullable=True),
        sa.Column("routing_mode", sa.String(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "audit_id",
            "score_dimension",
            name="uq_signal_audit_snapshots_audit_dimension",
        ),
    )
    op.create_index(
        "ix_signal_audit_snapshots_id",
        "signal_audit_snapshots",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_audit_snapshots_audit_id",
        "signal_audit_snapshots",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_audit_snapshots_project_id",
        "signal_audit_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_audit_snapshots_workspace_id",
        "signal_audit_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_audit_snapshots_snapshot_date",
        "signal_audit_snapshots",
        ["snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_signal_audit_snapshots_project_date",
        "signal_audit_snapshots",
        ["project_id", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_signal_audit_snapshots_workspace_date",
        "signal_audit_snapshots",
        ["workspace_id", "snapshot_date"],
        unique=False,
    )

    op.create_table(
        "signal_citation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "visibility_run_batch_id",
            sa.Integer(),
            sa.ForeignKey("visibility_run_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "visibility_run_id",
            sa.Integer(),
            sa.ForeignKey("visibility_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("query_hash", sa.String(), nullable=False),
        sa.Column("domain_cited", sa.String(), nullable=True),
        sa.Column("citation_present", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("answer_changed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("citations_hash", sa.String(), nullable=True),
        sa.Column("text_similarity_score", sa.Float(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "visibility_run_id",
            name="uq_signal_citation_events_visibility_run",
        ),
    )
    op.create_index(
        "ix_signal_citation_events_id",
        "signal_citation_events",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_citation_events_visibility_run_batch_id",
        "signal_citation_events",
        ["visibility_run_batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_citation_events_visibility_run_id",
        "signal_citation_events",
        ["visibility_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_citation_events_project_id",
        "signal_citation_events",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_citation_events_snapshot_date",
        "signal_citation_events",
        ["snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_signal_citation_events_query_hash",
        "signal_citation_events",
        ["query_hash"],
        unique=False,
    )
    op.create_index(
        "ix_signal_citation_events_project_date",
        "signal_citation_events",
        ["project_id", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_signal_citation_events_project_provider_date",
        "signal_citation_events",
        ["project_id", "provider", "snapshot_date"],
        unique=False,
    )

    op.create_table(
        "signal_entity_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id",
            sa.Integer(),
            sa.ForeignKey("audits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("entity_category", sa.String(), nullable=False, server_default="Unknown"),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("mention_frequency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "audit_id",
            "entity_key",
            name="uq_signal_entity_observations_audit_entity",
        ),
    )
    op.create_index(
        "ix_signal_entity_observations_id",
        "signal_entity_observations",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_entity_observations_audit_id",
        "signal_entity_observations",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_entity_observations_project_id",
        "signal_entity_observations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_entity_observations_snapshot_date",
        "signal_entity_observations",
        ["snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_signal_entity_observations_project_date",
        "signal_entity_observations",
        ["project_id", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_signal_entity_observations_entity_key",
        "signal_entity_observations",
        ["entity_key"],
        unique=False,
    )

    op.create_table(
        "signal_remediation_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_task_id",
            sa.Integer(),
            sa.ForeignKey("project_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recommendation_category", sa.String(), nullable=True),
        sa.Column("before_score_geo", sa.Float(), nullable=True),
        sa.Column("after_score_geo", sa.Float(), nullable=True),
        sa.Column("score_delta_geo", sa.Float(), nullable=True),
        sa.Column("before_score_aeo", sa.Float(), nullable=True),
        sa.Column("after_score_aeo", sa.Float(), nullable=True),
        sa.Column("score_delta_aeo", sa.Float(), nullable=True),
        sa.Column("days_to_impact", sa.Integer(), nullable=True),
        sa.Column(
            "audit_before_id",
            sa.Integer(),
            sa.ForeignKey("audits.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "audit_after_id",
            sa.Integer(),
            sa.ForeignKey("audits.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "project_task_id",
            "audit_after_id",
            name="uq_signal_remediation_outcomes_task_after_audit",
        ),
    )
    op.create_index(
        "ix_signal_remediation_outcomes_id",
        "signal_remediation_outcomes",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_remediation_outcomes_project_task_id",
        "signal_remediation_outcomes",
        ["project_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_remediation_outcomes_project_id",
        "signal_remediation_outcomes",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_remediation_outcomes_audit_before_id",
        "signal_remediation_outcomes",
        ["audit_before_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_remediation_outcomes_audit_after_id",
        "signal_remediation_outcomes",
        ["audit_after_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_remediation_outcomes_project_completed",
        "signal_remediation_outcomes",
        ["project_id", "completed_at"],
        unique=False,
    )

    op.create_table(
        "benchmark_cohort_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cohort_key", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("cohort_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p10", sa.Float(), nullable=True),
        sa.Column("p25", sa.Float(), nullable=True),
        sa.Column("p50", sa.Float(), nullable=True),
        sa.Column("p75", sa.Float(), nullable=True),
        sa.Column("p90", sa.Float(), nullable=True),
        sa.Column("mean", sa.Float(), nullable=True),
        sa.Column("stddev", sa.Float(), nullable=True),
        sa.Column("suppressed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "cohort_key",
            "metric",
            "period_date",
            name="uq_benchmark_cohort_aggregates_key_metric_period",
        ),
    )
    op.create_index(
        "ix_benchmark_cohort_aggregates_id",
        "benchmark_cohort_aggregates",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_benchmark_cohort_aggregates_cohort_key",
        "benchmark_cohort_aggregates",
        ["cohort_key"],
        unique=False,
    )
    op.create_index(
        "ix_benchmark_cohort_aggregates_metric",
        "benchmark_cohort_aggregates",
        ["metric"],
        unique=False,
    )
    op.create_index(
        "ix_benchmark_cohort_aggregates_period_date",
        "benchmark_cohort_aggregates",
        ["period_date"],
        unique=False,
    )
    op.create_index(
        "ix_benchmark_cohort_aggregates_period_metric",
        "benchmark_cohort_aggregates",
        ["period_date", "metric"],
        unique=False,
    )

    op.create_table(
        "proprietary_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score_type", sa.String(), nullable=False),
        sa.Column("score_version", sa.String(), nullable=False, server_default="v1"),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("components", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("weights", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.String(), nullable=False, server_default="insufficient"),
        sa.Column("data_points_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "project_id",
            "score_type",
            "score_version",
            name="uq_proprietary_scores_project_type_version",
        ),
    )
    op.create_index(
        "ix_proprietary_scores_id",
        "proprietary_scores",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_proprietary_scores_project_id",
        "proprietary_scores",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_proprietary_scores_score_type",
        "proprietary_scores",
        ["score_type"],
        unique=False,
    )
    op.create_index(
        "ix_proprietary_scores_project_computed",
        "proprietary_scores",
        ["project_id", "computed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_proprietary_scores_project_computed", table_name="proprietary_scores")
    op.drop_index("ix_proprietary_scores_score_type", table_name="proprietary_scores")
    op.drop_index("ix_proprietary_scores_project_id", table_name="proprietary_scores")
    op.drop_index("ix_proprietary_scores_id", table_name="proprietary_scores")
    op.drop_table("proprietary_scores")

    op.drop_index(
        "ix_benchmark_cohort_aggregates_period_metric", table_name="benchmark_cohort_aggregates"
    )
    op.drop_index(
        "ix_benchmark_cohort_aggregates_period_date", table_name="benchmark_cohort_aggregates"
    )
    op.drop_index("ix_benchmark_cohort_aggregates_metric", table_name="benchmark_cohort_aggregates")
    op.drop_index(
        "ix_benchmark_cohort_aggregates_cohort_key", table_name="benchmark_cohort_aggregates"
    )
    op.drop_index("ix_benchmark_cohort_aggregates_id", table_name="benchmark_cohort_aggregates")
    op.drop_table("benchmark_cohort_aggregates")

    op.drop_index(
        "ix_signal_remediation_outcomes_project_completed", table_name="signal_remediation_outcomes"
    )
    op.drop_index(
        "ix_signal_remediation_outcomes_audit_after_id", table_name="signal_remediation_outcomes"
    )
    op.drop_index(
        "ix_signal_remediation_outcomes_audit_before_id", table_name="signal_remediation_outcomes"
    )
    op.drop_index(
        "ix_signal_remediation_outcomes_project_id", table_name="signal_remediation_outcomes"
    )
    op.drop_index(
        "ix_signal_remediation_outcomes_project_task_id", table_name="signal_remediation_outcomes"
    )
    op.drop_index("ix_signal_remediation_outcomes_id", table_name="signal_remediation_outcomes")
    op.drop_table("signal_remediation_outcomes")

    op.drop_index(
        "ix_signal_entity_observations_entity_key", table_name="signal_entity_observations"
    )
    op.drop_index(
        "ix_signal_entity_observations_project_date", table_name="signal_entity_observations"
    )
    op.drop_index(
        "ix_signal_entity_observations_snapshot_date", table_name="signal_entity_observations"
    )
    op.drop_index(
        "ix_signal_entity_observations_project_id", table_name="signal_entity_observations"
    )
    op.drop_index("ix_signal_entity_observations_audit_id", table_name="signal_entity_observations")
    op.drop_index("ix_signal_entity_observations_id", table_name="signal_entity_observations")
    op.drop_table("signal_entity_observations")

    op.drop_index(
        "ix_signal_citation_events_project_provider_date", table_name="signal_citation_events"
    )
    op.drop_index("ix_signal_citation_events_project_date", table_name="signal_citation_events")
    op.drop_index("ix_signal_citation_events_query_hash", table_name="signal_citation_events")
    op.drop_index("ix_signal_citation_events_snapshot_date", table_name="signal_citation_events")
    op.drop_index("ix_signal_citation_events_project_id", table_name="signal_citation_events")
    op.drop_index(
        "ix_signal_citation_events_visibility_run_id", table_name="signal_citation_events"
    )
    op.drop_index(
        "ix_signal_citation_events_visibility_run_batch_id", table_name="signal_citation_events"
    )
    op.drop_index("ix_signal_citation_events_id", table_name="signal_citation_events")
    op.drop_table("signal_citation_events")

    op.drop_index("ix_signal_audit_snapshots_workspace_date", table_name="signal_audit_snapshots")
    op.drop_index("ix_signal_audit_snapshots_project_date", table_name="signal_audit_snapshots")
    op.drop_index("ix_signal_audit_snapshots_snapshot_date", table_name="signal_audit_snapshots")
    op.drop_index("ix_signal_audit_snapshots_workspace_id", table_name="signal_audit_snapshots")
    op.drop_index("ix_signal_audit_snapshots_project_id", table_name="signal_audit_snapshots")
    op.drop_index("ix_signal_audit_snapshots_audit_id", table_name="signal_audit_snapshots")
    op.drop_index("ix_signal_audit_snapshots_id", table_name="signal_audit_snapshots")
    op.drop_table("signal_audit_snapshots")
