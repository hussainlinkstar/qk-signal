"""SIGV2-1272: SMTP settings can live only in the DB section, and a database
rebuild then silently removes all transactional email. The health surface and
the startup warning must say so. Resolution-only tests: nothing here may open
an SMTP connection.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

import system_checks
from services.email_sender import missing_smtp_settings

_ENV_KEYS = (
    "SMTP_HOST",
    "MAIL_SERVER",
    "SMTP_USERNAME",
    "MAIL_USERNAME",
    "SMTP_PASSWORD",
    "MAIL_PASSWORD",
)


def _clear_smtp_env(monkeypatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _set_smtp_env(monkeypatch, *, omit: tuple[str, ...] = ()) -> None:
    values = {"SMTP_HOST": "smtp.example.com", "SMTP_USERNAME": "u@x.com", "SMTP_PASSWORD": "pw"}
    for key, value in values.items():
        if key not in omit:
            monkeypatch.setenv(key, value)


def _db_section(monkeypatch, section: dict | None) -> None:
    """Patch the DB-section lookup _load_config consults."""

    def fake_get_section(_section: str, _db):
        return dict(section or {})

    monkeypatch.setattr("core.db_settings_resolver.get_section", fake_get_section)


def test_operational_when_all_three_resolve(monkeypatch):
    _clear_smtp_env(monkeypatch)
    _set_smtp_env(monkeypatch)
    status, details = system_checks._email_transport_status(None)
    assert status == "Operational"
    assert details == ""


@pytest.mark.parametrize(
    "omit,missing_label",
    [
        (("SMTP_HOST",), "smtp_host"),
        (("SMTP_USERNAME",), "smtp_username"),
        (("SMTP_PASSWORD",), "smtp_password"),
    ],
)
def test_not_configured_names_the_missing_key(monkeypatch, omit, missing_label):
    _clear_smtp_env(monkeypatch)
    _set_smtp_env(monkeypatch, omit=omit)
    _db_section(monkeypatch, {})
    status, details = system_checks._email_transport_status(object())
    assert status == "Not Configured"
    assert missing_label in details


def test_all_three_missing(monkeypatch):
    _clear_smtp_env(monkeypatch)
    _db_section(monkeypatch, {})
    status, details = system_checks._email_transport_status(object())
    assert status == "Not Configured"
    for label in ("smtp_host", "smtp_username", "smtp_password"):
        assert label in details


def test_db_section_alone_reports_operational(monkeypatch):
    """A rebuilt-env scenario: SMTP held only in the DB section is a
    legitimate configuration and must not report Not Configured."""
    _clear_smtp_env(monkeypatch)
    _db_section(
        monkeypatch,
        {"smtp_host": "smtp.gmail.com", "smtp_username": "support@x.com", "smtp_password": "pw"},
    )
    status, details = system_checks._email_transport_status(object())
    assert status == "Operational"


def test_startup_warning_fires_when_incomplete(monkeypatch, caplog):
    _clear_smtp_env(monkeypatch)
    _db_section(monkeypatch, {})
    with caplog.at_level(logging.WARNING, logger="system_checks"):
        system_checks.warn_if_email_transport_unconfigured(object())
    assert any("email_transport_not_configured" in record.getMessage() for record in caplog.records)


def test_startup_warning_silent_when_complete(monkeypatch, caplog):
    _clear_smtp_env(monkeypatch)
    _set_smtp_env(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="system_checks"):
        system_checks.warn_if_email_transport_unconfigured(None)
    assert not any(
        "email_transport_not_configured" in record.getMessage() for record in caplog.records
    )


def test_missing_smtp_settings_lists_env_aliases(monkeypatch):
    _clear_smtp_env(monkeypatch)
    missing = missing_smtp_settings(None)
    assert "SMTP_HOST" in missing[0]
    assert len(missing) == 3
