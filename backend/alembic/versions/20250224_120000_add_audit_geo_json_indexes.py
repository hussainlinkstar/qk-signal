"""add functional GEO JSON indexes for audit performance

Revision ID: 20250224_120000
Revises: 20250223_120000
Create Date: 2025-02-24 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20250224_120000"
down_revision: Union[str, None] = "20250223_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_audits_geo_visibility_index_expr
        ON audits (((full_report::jsonb -> 'geo' ->> 'visibility_index')::double precision))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_audits_geo_citation_share_expr
        ON audits (((full_report::jsonb -> 'geo' ->> 'citation_share')::double precision))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_audits_geo_brand_anchor_expr
        ON audits (((full_report::jsonb -> 'geo' ->> 'brand_anchor')::double precision))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_audits_geo_brand_anchor_expr")
    op.execute("DROP INDEX IF EXISTS ix_audits_geo_citation_share_expr")
    op.execute("DROP INDEX IF EXISTS ix_audits_geo_visibility_index_expr")
