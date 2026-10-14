"""add site competitors association table

Revision ID: 20250225_120000
Revises: 20250224_120000
Create Date: 2025-02-25 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250225_120000"
down_revision: Union[str, None] = "20250224_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_competitors",
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("competitor_site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["competitor_site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("site_id", "competitor_site_id", name="uq_site_competitors_pair"),
    )
    op.create_index("ix_site_competitors_site_id", "site_competitors", ["site_id"], unique=False)
    op.create_index(
        "ix_site_competitors_competitor_site_id",
        "site_competitors",
        ["competitor_site_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_site_competitors_competitor_site_id", table_name="site_competitors")
    op.drop_index("ix_site_competitors_site_id", table_name="site_competitors")
    op.drop_table("site_competitors")
