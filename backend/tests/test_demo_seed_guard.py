"""The demo seed scripts write fabricated figures, so they must refuse to run
against anything but a local database. These tests cover that gate:
``scripts/_demo_seed_guard.assert_local_database``.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _demo_seed_guard import OPT_IN, assert_local_database  # noqa: E402

URL_VARS = ("DATABASE_URL", "SQLALCHEMY_DATABASE_URL", "POSTGRES_URL")


@pytest.fixture(autouse=True)
def _clean_db_env(monkeypatch):
    for var in (*URL_VARS, OPT_IN):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://signal:secret@localhost:5432/signal",
        "postgresql+psycopg://signal:secret@127.0.0.1:5432/signal",
        "postgresql://signal:secret@db:5432/signal",
        "postgresql://signal:secret@postgres:5432/signal",
        "postgresql://signal:secret@signal-db:5432/signal",
    ],
)
def test_allows_local_hosts(url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", url)
    assert_local_database()  # does not raise


def test_refuses_remote_host(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://signal:secret@cluster.abc123.eu-west-1.rds.amazonaws.com:5432/signal",
    )
    with pytest.raises(SystemExit):
        assert_local_database()


def test_remote_host_allowed_with_explicit_opt_in(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://signal:secret@cluster.abc123.eu-west-1.rds.amazonaws.com:5432/signal",
    )
    monkeypatch.setenv(OPT_IN, "yes")
    assert_local_database()  # does not raise
    assert "WARNING" in capsys.readouterr().out


def test_remote_host_refuses_wrong_opt_in_value(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://signal:secret@cluster.abc123.eu-west-1.rds.amazonaws.com:5432/signal",
    )
    monkeypatch.setenv(OPT_IN, "true")
    with pytest.raises(SystemExit):
        assert_local_database()


def test_refuses_missing_database_url():
    with pytest.raises(SystemExit):
        assert_local_database()


def test_refuses_url_without_host(monkeypatch):
    # A URL carrying no hostname cannot be confirmed local, so it is refused
    # rather than silently allowed.
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/local.db")
    with pytest.raises(SystemExit):
        assert_local_database()


def test_falls_back_to_alternate_url_env_vars(monkeypatch):
    monkeypatch.setenv(
        "SQLALCHEMY_DATABASE_URL",
        "postgresql://signal:secret@cluster.abc123.eu-west-1.rds.amazonaws.com:5432/signal",
    )
    with pytest.raises(SystemExit):
        assert_local_database()
