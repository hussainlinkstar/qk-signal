"""add performance snapshots table

Revision ID: 20250222_120000
Revises: 20250221_120000
Create Date: 2025-02-22 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250222_120000"
down_revision: Union[str, None] = "20250221_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "performance_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("normalized_url", sa.String(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("metrics_payload", sa.JSON(), nullable=False),
        sa.Column("source_status", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_url", "snapshot_date", name="uq_performance_snapshots_url_date"
        ),
    )
    op.create_index(
        op.f("ix_performance_snapshots_id"), "performance_snapshots", ["id"], unique=False
    )
    op.create_index(
        "ix_performance_snapshots_snapshot_date",
        "performance_snapshots",
        ["snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_performance_snapshots_url_date",
        "performance_snapshots",
        ["normalized_url", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_performance_snapshots_normalized_url"),
        "performance_snapshots",
        ["normalized_url"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_performance_snapshots_normalized_url"), table_name="performance_snapshots"
    )
    op.drop_index("ix_performance_snapshots_url_date", table_name="performance_snapshots")
    op.drop_index("ix_performance_snapshots_snapshot_date", table_name="performance_snapshots")
    op.drop_index(op.f("ix_performance_snapshots_id"), table_name="performance_snapshots")
    op.drop_table("performance_snapshots")
