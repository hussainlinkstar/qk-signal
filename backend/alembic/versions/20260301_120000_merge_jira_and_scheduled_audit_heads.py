"""merge jira and scheduled audit heads

Revision ID: 20260301_120000
Revises: 1e200753157f, 20250319_120000
Create Date: 2026-03-01 12:00:00.000000

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "20260301_120000"
down_revision: Union[str, Sequence[str], None] = ("1e200753157f", "20250319_120000")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
