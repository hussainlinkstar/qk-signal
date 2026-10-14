"""merge_heads_20260305

Revision ID: 7b61608e95c4
Revises: 20260305_000000, 20260305_170000
Create Date: 2026-03-05 23:55:40.630965

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "7b61608e95c4"
down_revision: Union[str, None] = ("20260305_000000", "20260305_170000")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
