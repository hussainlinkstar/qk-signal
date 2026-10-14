"""SIGV2-1271: scripts/create_admin.py is the only tool that can bootstrap the
first admin on a fresh environment, so it must run against the deployed driver
set (no asyncpg) and the live schema (no hand-written column list). These tests
run the script as a subprocess against a real database file so schema drift
breaks CI instead of a launch night.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from core.password_hashing import verify_password

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_admin.py"

ADMIN_EMAIL = "root@example.com"
ADMIN_PASSWORD = "Sup3r-Secret!"


def _run_script(db_url: str | None, args: tuple = (), extra_env: dict | None = None):
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "DATABASE_URL")
    }
    if extra_env:
        env.update(extra_env)
    if db_url is not None:
        env["DATABASE_URL"] = db_url
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _fetch_user(db_url: str, email: str):
    engine = create_engine(db_url)
    session = sessionmaker(bind=engine)()
    try:
        return session.query(models.User).filter(models.User.email == email).first()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def db_url(tmp_path):
    """An empty but fully-migrated database file (schema straight from the
    ORM metadata, the same convention as the rest of the suite)."""
    url = f"sqlite:///{tmp_path / 'admin_bootstrap.db'}"
    engine = create_engine(url)
    models.Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def admin_env():
    return {"ADMIN_EMAIL": ADMIN_EMAIL, "ADMIN_PASSWORD": ADMIN_PASSWORD}


def test_creates_admin_on_empty_database(db_url, admin_env):
    result = _run_script(db_url, extra_env=admin_env)
    assert result.returncode == 0, result.stderr
    assert ADMIN_PASSWORD not in result.stdout
    assert ADMIN_PASSWORD not in result.stderr

    user = _fetch_user(db_url, ADMIN_EMAIL)
    assert user is not None
    assert user.role == "admin"
    assert user.email_verified is True
    assert verify_password(ADMIN_PASSWORD, user.hashed_password)


def test_existing_user_is_untouched_without_reset_password(db_url, admin_env):
    assert _run_script(db_url, extra_env=admin_env).returncode == 0
    original = _fetch_user(db_url, ADMIN_EMAIL)
    original_hash = original.hashed_password

    result = _run_script(
        db_url,
        extra_env={"ADMIN_EMAIL": ADMIN_EMAIL, "ADMIN_PASSWORD": "DifferentPass1!"},
    )
    assert result.returncode == 0, result.stderr
    assert "nothing changed" in result.stdout

    user = _fetch_user(db_url, ADMIN_EMAIL)
    assert user.hashed_password == original_hash
    assert user.role == "admin"


def test_reset_password_updates_hash_and_role(db_url):
    assert (
        _run_script(
            db_url,
            extra_env={
                "ADMIN_EMAIL": ADMIN_EMAIL,
                "ADMIN_PASSWORD": "FirstPass1!",
            },
        ).returncode
        == 0
    )
    # Demote the user so the reset path must also restore the admin role.
    engine = create_engine(db_url)
    session = sessionmaker(bind=engine)()
    user = session.query(models.User).filter(models.User.email == ADMIN_EMAIL).first()
    user.role = "user"
    session.commit()
    session.close()
    engine.dispose()

    result = _run_script(
        db_url,
        args=("--reset-password",),
        extra_env={"ADMIN_EMAIL": ADMIN_EMAIL, "ADMIN_PASSWORD": "SecondPass2!"},
    )
    assert result.returncode == 0, result.stderr

    user = _fetch_user(db_url, ADMIN_EMAIL)
    assert user.role == "admin"
    assert user.email_verified is True
    assert verify_password("SecondPass2!", user.hashed_password)


def test_missing_env_vars_exit_nonzero_without_touching_db(db_url):
    # No ADMIN_EMAIL / ADMIN_PASSWORD in the environment at all.
    result = _run_script(db_url)
    assert result.returncode != 0
    assert "ADMIN_EMAIL" in result.stderr

    engine = create_engine(db_url)
    session = sessionmaker(bind=engine)()
    try:
        assert session.query(models.User).count() == 0
    finally:
        session.close()
        engine.dispose()
