"""Refuse to run a demo seed anywhere but a local development database.

The demo seeds write fabricated figures. Matching on the project id and domain
is not enough on its own: a deployed environment can hold a project with the
same id and the same domain, and the seed would then overwrite real audits with
demo numbers. So the gate is the database host, which a deployed environment
never shares with a laptop, plus an explicit opt-in for the unusual case.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres", "signal-db"}
OPT_IN = "QIKO_ALLOW_DEMO_SEED"


def assert_local_database() -> None:
    """Raise SystemExit unless this process points at a local database."""
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("SQLALCHEMY_DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or ""
    )
    if not url:
        raise SystemExit(
            "Refusing to seed: no database URL in the environment, so the target "
            "cannot be confirmed local. Set DATABASE_URL explicitly."
        )

    host = (urlparse(url).hostname or "").lower()
    if host in LOCAL_HOSTS:
        return

    if os.environ.get(OPT_IN) == "yes":
        print(
            f"WARNING: seeding demo data against non-local host {host!r} "
            f"because {OPT_IN}=yes was set."
        )
        return

    raise SystemExit(
        f"Refusing to seed: database host {host!r} is not local. Demo seeds write\n"
        f"fabricated figures and would overwrite real audits. If this really is a\n"
        f"throwaway environment, re-run with {OPT_IN}=yes."
    )
