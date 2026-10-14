import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


@dataclass(frozen=True)
class EmailConfig:
    from_email: str
    from_name: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_username: str | None
    smtp_password: str | None


def _load_config(db=None) -> EmailConfig:
    """Load SMTP email config from DB (if db is provided) with fallback to env vars."""
    db_section: dict = {}
    if db is not None:
        try:
            from core.db_settings_resolver import get_section, SECTION_EMAIL_CONFIG

            db_section = get_section(SECTION_EMAIL_CONFIG, db)
        except Exception:
            pass

    def _get(*env_keys: str, db_key: str = "", default: str = "") -> str:
        if db_key and db_section:
            val = db_section.get(db_key)
            if val is not None and str(val).strip():
                return str(val).strip()
        for k in env_keys:
            v = (os.getenv(k) or "").strip()
            if v:
                return v
        return default

    from_email = _get(
        "EMAIL_FROM_ADDRESS",
        "MAIL_FROM",
        db_key="from_address",
        default="no-reply@example.com",
    )
    from_name = _get("EMAIL_FROM_NAME", "MAIL_FROM_NAME", db_key="from_name") or None

    smtp_port_str = _get("SMTP_PORT", "MAIL_PORT", db_key="smtp_port", default="587")
    try:
        smtp_port = int(smtp_port_str)
    except (TypeError, ValueError):
        smtp_port = 587

    return EmailConfig(
        from_email=from_email,
        from_name=from_name,
        smtp_host=_get("SMTP_HOST", "MAIL_SERVER", db_key="smtp_host") or None,
        smtp_port=smtp_port,
        smtp_username=_get("SMTP_USERNAME", "MAIL_USERNAME", db_key="smtp_username") or None,
        smtp_password=_get("SMTP_PASSWORD", "MAIL_PASSWORD", db_key="smtp_password") or None,
    )


# The transport only works when all three resolve; each maps to the DB
# section key plus the environment aliases _load_config consults, in order.
_SMTP_REQUIRED_KEYS: tuple[tuple[str, str], ...] = (
    ("smtp_host", "SMTP_HOST/MAIL_SERVER"),
    ("smtp_username", "SMTP_USERNAME/MAIL_USERNAME"),
    ("smtp_password", "SMTP_PASSWORD/MAIL_PASSWORD"),
)


def missing_smtp_settings(db=None) -> list[str]:
    """Return the SMTP keys that resolve nowhere (DB email section or env).

    Resolution-only: reuses ``_load_config`` so health checks and startup
    warnings describe exactly what sending would get, and never opens a
    socket. SIGV2-1272.
    """
    config = _load_config(db)
    return [
        f"{key} ({env_hint})" for key, env_hint in _SMTP_REQUIRED_KEYS if not getattr(config, key)
    ]


def _smtp_send(
    config: EmailConfig,
    to: str,
    subject: str,
    html: str | None,
    text: str | None,
    from_name: str | None,
    reply_to: str | None,
) -> dict[str, Any]:
    if not config.smtp_host:
        raise ValueError("SMTP_HOST is required to send email.")
    if not config.smtp_username or not config.smtp_password:
        raise ValueError(
            "SMTP credentials (SMTP_USERNAME / SMTP_PASSWORD) are required to send email."
        )

    message = EmailMessage()
    from_display = config.from_email
    effective_from_name = from_name if from_name is not None else config.from_name
    if effective_from_name:
        from_display = f"{effective_from_name} <{config.from_email}>"
    message["From"] = from_display
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to

    if text:
        message.set_content(text)
    if html:
        if text:
            message.add_alternative(html, subtype="html")
        else:
            message.set_content(html, subtype="html")

    smtp_port = config.smtp_port or 587
    use_ssl = smtp_port == 465
    smtp_client = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    with smtp_client(config.smtp_host, smtp_port) as smtp:
        if not use_ssl:
            smtp.starttls()
        smtp.login(config.smtp_username, config.smtp_password)
        smtp.send_message(message)

    return {"provider": "smtp"}


def send(
    to: str,
    subject: str,
    html: str | None,
    text: str | None,
    category: str | None,
    correlation_id: str | None,
    from_name: str | None = None,
    reply_to: str | None = None,
    db=None,
) -> dict[str, Any]:
    """Send a transactional email over SMTP."""
    config = _load_config(db)
    result = _smtp_send(config, to, subject, html, text, from_name, reply_to)
    result.update({"category": category, "correlation_id": correlation_id})
    return result
