"""Clear self-referential provider_subject / external_id on users (SIGV2-1268).

Until SIGV2-1268, ``auth/token_verifier.py::_resolve_user_from_claims``
rewrote ``users.provider_subject`` and ``users.external_id`` to the access
token's ``sub`` on every authenticated request. Our access tokens are minted
by ``services.auth_service.create_access_token`` with ``sub = str(user.id)``,
so after a single authenticated request both columns held the row's own id
rendered as text, not the provider's subject. Because ``provider_subject``
carries a unique constraint, every SSO user's row converged on a value
derived from its own id.

This is a DATA-ONLY migration:

* no column added, dropped, renamed or retyped;
* no constraint added or removed;
* two UPDATEs setting the columns to NULL where the stored value equals the
  row's own id cast to text. That value is provably ours and not a
  provider's, and clearing it frees the unique-constraint space for a real
  subject later.

No recovery of the real provider subjects is attempted: they were
overwritten and are gone. ``user_linked_identities`` (20261018_010000)
carries the truth going forward.

The migration is idempotent: a second run finds no rows matching
``provider_subject = id::text`` / ``external_id = id::text`` and updates
nothing.

``downgrade()`` is a documented no-op with no recoverable inverse: once
cleared, nothing distinguishes a NULL produced by this migration from a NULL
that was always empty, and the destroyed provider subjects cannot be
reconstructed from local data.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261019_010000"
down_revision = "20261018_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("users")}

    for column in ("provider_subject", "external_id"):
        if column not in columns:
            continue
        bind.execute(sa.text(f"UPDATE users SET {column} = NULL WHERE {column} = CAST(id AS TEXT)"))


def downgrade() -> None:
    # No recoverable inverse: the values cleared here were our own user ids,
    # not provider subjects, and there is no stored record of which rows had
    # them. See the module docstring.
    pass
