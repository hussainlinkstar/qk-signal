"""Deliberate operator bootstrap tool for the first admin account.

Usage: ADMIN_EMAIL, ADMIN_PASSWORD and DATABASE_URL must all be set in the
environment; pass --reset-password to change an existing user's password.

The previous version of this script hashed a password hardcoded in this
repository at module import, printed it to stdout, and, if the hardcoded
email already existed, silently overwrote that user's hashed_password and
role. Pointed at a real database that was an account takeover plus a
privilege escalation whose credential was published in git. The literal is
deliberately not repeated here: if that script was ever run against a
deployed environment, it is a live credential on that account and belongs in
a rotation, not in a docstring. See the git history for specifics.

That history is why this version looks paranoid: every input is explicit
with no defaults or fallbacks, importing the module has no side effects, the
password is never printed, and overwriting an existing account is opt-in via
--reset-password. Do not tidy any of that away.

The user row is written through ``models.User`` rather than a hand-written
column list, and the engine uses the synchronous driver that is actually
installed (psycopg2), not ``postgresql+asyncpg``. A raw INSERT referencing a
dropped column (``is_active``) and an async driver absent from the deployed
image are what broke this tool in production (SIGV2-1271); the ORM is the
schema's own description, so it cannot drift the same way.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from core.password_hashing import hash_password


def _require_env() -> tuple[str, str, str]:
    missing = [
        name
        for name in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "DATABASE_URL")
        if not os.environ.get(name)
    ]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    # The email is an identifier, so strip it. The password is not: leading or
    # trailing spaces are legitimate, so only reject an all-whitespace one.
    email = os.environ["ADMIN_EMAIL"].strip()
    password = os.environ["ADMIN_PASSWORD"]
    if not email:
        print("ADMIN_EMAIL is empty or whitespace-only", file=sys.stderr)
        sys.exit(1)
    if not password.strip():
        print("ADMIN_PASSWORD is empty or whitespace-only", file=sys.stderr)
        sys.exit(1)
    return email, password, os.environ["DATABASE_URL"]


def _sync_database_url(url: str) -> str:
    # The deployed image ships psycopg2 only; an asyncpg URL must not reach
    # the sync engine.
    return url.replace("postgresql+asyncpg://", "postgresql://")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first admin user")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="overwrite the password and role of an existing user",
    )
    args = parser.parse_args()

    email, password, db_url = _require_env()
    hashed = hash_password(password)

    engine = create_engine(_sync_database_url(db_url))
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        user = session.query(models.User).filter(models.User.email == email).first()

        if user is None:
            session.add(
                models.User(
                    email=email,
                    hashed_password=hashed,
                    role="admin",
                    email_verified=True,
                )
            )
            session.commit()
            print(f"Admin user created: {email}")
        elif not args.reset_password:
            print(
                f"User {email} already exists; nothing changed. Pass --reset-password to overwrite its password and role."
            )
        else:
            user.role = "admin"
            user.email_verified = True
            user.hashed_password = hashed
            session.commit()
            print(f"User {email} updated: role set to admin, password reset.")

    engine.dispose()


if __name__ == "__main__":
    main()
