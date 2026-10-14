import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.email_sender import _load_config  # noqa: E402


def test_load_config_reads_smtp_env(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "support@qiko.ai")
    monkeypatch.setenv("EMAIL_FROM_NAME", "Qiko Signal")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "support@qiko.ai")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")

    config = _load_config()

    assert config.from_email == "support@qiko.ai"
    assert config.from_name == "Qiko Signal"
    assert config.smtp_host == "smtp.gmail.com"
    assert config.smtp_port == 587
    assert config.smtp_username == "support@qiko.ai"
    assert config.smtp_password == "app-password"


def test_load_config_accepts_legacy_mail_env_aliases(monkeypatch) -> None:
    # _load_config() checks canonical env vars before the legacy MAIL_* aliases.
    # The runtime container ships canonical EMAIL_FROM_*/SMTP_* values, so clear
    # them to exercise the legacy alias fallback path.
    for canonical in (
        "EMAIL_FROM_ADDRESS",
        "EMAIL_FROM_NAME",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
    ):
        monkeypatch.delenv(canonical, raising=False)

    monkeypatch.setenv("MAIL_FROM", "legacy-from@example.com")
    monkeypatch.setenv("MAIL_FROM_NAME", "Legacy Sender")
    monkeypatch.setenv("MAIL_SERVER", "smtp.legacy.test")
    monkeypatch.setenv("MAIL_PORT", "2525")
    monkeypatch.setenv("MAIL_USERNAME", "legacy-user")
    monkeypatch.setenv("MAIL_PASSWORD", "legacy-pass")

    config = _load_config()

    assert config.from_email == "legacy-from@example.com"
    assert config.from_name == "Legacy Sender"
    assert config.smtp_host == "smtp.legacy.test"
    assert config.smtp_port == 2525
    assert config.smtp_username == "legacy-user"
    assert config.smtp_password == "legacy-pass"
