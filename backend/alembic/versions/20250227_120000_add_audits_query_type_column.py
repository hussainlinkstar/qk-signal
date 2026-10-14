"""add audits query_type column

Revision ID: 20250227_120000
Revises: 20250226_120000
Create Date: 2025-02-27 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250227_120000"
down_revision: Union[str, None] = "20250226_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audits", sa.Column("query_type", sa.String(), nullable=True))
    op.create_index("ix_audits_query_type", "audits", ["query_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audits_query_type", table_name="audits")
    op.drop_column("audits", "query_type")
