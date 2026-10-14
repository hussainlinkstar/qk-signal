"""merge dual heads 20260323_080000 and 20260404_150000

Revision ID: bc2d29a09e15
Revises: 20260323_080000, 20260404_150000
Create Date: 2026-04-17 23:58:53.922778

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "20260417_235800"
down_revision: Union[str, None] = ("20260323_080000", "20260404_150000")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
