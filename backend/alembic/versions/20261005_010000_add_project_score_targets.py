"""Add nullable score-target columns on projects (SIGV2-1006).

Per-project AIO and SEO score targets. Fully additive and nullable: a NULL
means the project has no override and reads the product-configured default
from settings (PROJECT_DEFAULT_AIO_SCORE_TARGET / _SEO_SCORE_TARGET).

Revision ID: 20261005_010000
Revises: 20261004_010000
Create Date: 2026-10-05 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261005_010000"
down_revision = "20261004_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("projects")}
    if "aio_score_target" not in columns:
        op.add_column("projects", sa.Column("aio_score_target", sa.Integer(), nullable=True))
    if "seo_score_target" not in columns:
        op.add_column("projects", sa.Column("seo_score_target", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("projects")}
    if "seo_score_target" in columns:
        op.drop_column("projects", "seo_score_target")
    if "aio_score_target" in columns:
        op.drop_column("projects", "aio_score_target")
