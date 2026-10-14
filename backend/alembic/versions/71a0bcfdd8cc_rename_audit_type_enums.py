"""rename_audit_type_enums

Revision ID: 71a0bcfdd8cc
Revises: 20250318_120000
Create Date: 2026-02-27 03:46:10.909991

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "71a0bcfdd8cc"
down_revision: Union[str, None] = "20250318_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Note: audit_type uses native_enum=False (stored as VARCHAR), so we need UPDATE statements
    # not ALTER TYPE. But since we now support all values, this migration is a no-op.
    # The Python enum now includes both old and new values for backward compatibility.
    pass


def downgrade() -> None:
    # No-op since we're keeping all enum values for compatibility
    pass
