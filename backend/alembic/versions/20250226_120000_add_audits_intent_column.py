"""add audits intent column

Revision ID: 20250226_120000
Revises: 20250225_120000
Create Date: 2025-02-26 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250226_120000"
down_revision: Union[str, None] = "20250225_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audits", sa.Column("intent", sa.String(), nullable=True))
    op.create_index("ix_audits_intent", "audits", ["intent"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audits_intent", table_name="audits")
    op.drop_column("audits", "intent")
