"""Add audit_tier_duration_stats (SIGV2-1177).

The product states a runtime per depth. Until now that figure came from a
constant: SIGV2-1161 removed one set of invented numbers and put the approved
design's in their place, which is a real source but not a measurement. This
table is where the measurement lives, so the surface can state a figure derived
from runs that actually happened.

One row per selectable depth (``fast``, ``smart``, ``deep_judgment``), upserted
by the hourly cron sweep from completed ``audit_jobs`` runs. The quartiles are
nullable on purpose: they stay NULL until a tier clears its minimum sample
size, which is what guarantees no surface can publish a figure derived from a
handful of runs. The statistic, the exclusions and the thresholds are documented
in ``backend/services/tier_duration_stats_service.py``.

Additive only: one new table. Nothing is dropped, renamed or made NOT NULL on an
existing table, and no existing row anywhere is rewritten. No index beyond the
unique constraint on ``tier``: the table holds one row per tier (three today),
and every read is "give me all of them".

Revision ID: 20261014_010000
Revises: 20261013_010000
Create Date: 2026-10-14 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261014_010000"
down_revision = "20261013_010000"
branch_labels = None
depends_on = None

TABLE_NAME = "audit_tier_duration_stats"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME in set(inspector.get_table_names()):
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("min_sample_size", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("p25_seconds", sa.Float(), nullable=True),
        sa.Column("p50_seconds", sa.Float(), nullable=True),
        sa.Column("p75_seconds", sa.Float(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tier", name="uq_audit_tier_duration_stats_tier"),
    )
    op.create_index(op.f("ix_audit_tier_duration_stats_id"), TABLE_NAME, ["id"], unique=False)
    op.create_index(op.f("ix_audit_tier_duration_stats_tier"), TABLE_NAME, ["tier"], unique=False)


def downgrade() -> None:
    """Drop the aggregate table.

    Safe to reverse: every value in it is derived from ``audit_jobs``, which is
    untouched, so the next sweep after a re-upgrade rebuilds the whole table
    from source. Nothing here is a system of record. Still never to be run
    against a live database (AGENTS.md 4.2); the code path above it would start
    serving nothing, which is the correct behaviour but not a quiet one.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    op.drop_index(op.f("ix_audit_tier_duration_stats_tier"), table_name=TABLE_NAME)
    op.drop_index(op.f("ix_audit_tier_duration_stats_id"), table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
