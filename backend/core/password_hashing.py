"""Password hashing via the bcrypt package directly.

This module exists because passlib 1.7.4 is unmaintained (no release since
October 2020) and pinned bcrypt to a narrow window it can load: bcrypt 4.1.0
and 5.0.0 both break passlib, so a bcrypt CVE could not be patched. The stored
hash format is unchanged ($2b$ cost 12), so every existing
``users.hashed_password`` keeps verifying with no migration and no forced
reset.

``_ROUNDS = 12`` is not a free choice. It is the cost passlib produced for
every hash already in the database. Lowering it weakens new hashes; raising
it is a deliberate decision, not a tidy-up.

The 72-byte truncation in ``_prepare`` is load-bearing, not a detail.
passlib's bcrypt handler truncates the UTF-8 encoded secret before hashing
(``truncate_size = 72`` in ``passlib/handlers/bcrypt.py``), and bcrypt itself
reads no further than 72 bytes. bcrypt >= 4.1 raises ``ValueError`` instead
of truncating, so dropping this would turn every password over 72 bytes,
which previously worked, into a 500 and lock those users out. Truncating at
the byte boundary can split a multibyte character; that is correct, because
passlib truncated the same way and the hashes still match.
"""

import logging

import bcrypt

logger = logging.getLogger(__name__)

_ROUNDS = 12
_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=_ROUNDS)).decode("ascii")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        # Return False rather than raising on a malformed or empty hash: it
        # matches the defensive pattern already at routers/api_router.py and
        # prevents a 500 on legacy non-bcrypt column values (some fixtures
        # carry hashed_password="x"). The warning makes a systematic failure
        # observable: if checkpw raised ValueError for a library-internal
        # reason, every valid password would otherwise be rejected silently.
        # Log the exception only, never the password or the stored hash.
        logger.warning(
            "password verification rejected a malformed hash: %s: %s", type(exc).__name__, exc
        )
        return False
