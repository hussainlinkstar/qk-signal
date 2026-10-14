#!/usr/bin/env python3
"""Queue a branded test email through the EmailOutbox (sent by the email worker).

Renders a real template with the rebranded Qiko Signal styling (logo + indigo→cyan
gradient) and enqueues it for delivery. The email worker picks up pending outbox
rows and sends them via SMTP (Gmail).

Run on the production backend container, e.g.:

    docker exec -i <backend-container> python -m scripts.send_test_email babarazvan@yahoo.com
    docker exec -i <backend-container> python -m scripts.send_test_email babarazvan@yahoo.com auth.welcome

Requires a configured email provider (MAIL_ENABLED + SMTP) and a running
email worker for actual delivery.
"""

from __future__ import annotations

import logging
import sys
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("send_test_email")

DEFAULT_RECIPIENT = "babarazvan@yahoo.com"
DEFAULT_TEMPLATE = "auth.welcome"


def main() -> int:
    to_email = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RECIPIENT).strip().lower()
    template_key = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TEMPLATE

    if "@" not in to_email:
        logger.error("Invalid recipient email: %s", to_email)
        return 2

    import models
    from database import SessionLocal
    from services.email_templates import (
        DEFAULT_PREVIEW_CONTEXT,
        TEMPLATE_DEFINITIONS,
        render_template,
    )

    if template_key not in TEMPLATE_DEFINITIONS:
        logger.error(
            "Unknown template key %r. Available: %s",
            template_key,
            ", ".join(sorted(TEMPLATE_DEFINITIONS)),
        )
        return 2

    rendered = render_template(template_key, dict(DEFAULT_PREVIEW_CONTEXT))

    db = SessionLocal()
    try:
        entry = models.EmailOutbox(
            to_email=to_email,
            subject=f"[TEST] {rendered.subject}",
            html_body=rendered.html,
            text_body=rendered.text,
            category=rendered.category,
            template_key=template_key,
            correlation_id=f"cli-test-{uuid4().hex[:12]}",
            status="pending",
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        logger.info(
            "Queued test email id=%s template=%s -> %s (subject: %s)",
            entry.id,
            template_key,
            to_email,
            entry.subject,
        )
        logger.info("The email worker will deliver it; check /admin/email-outbox for status.")
        return 0
    except Exception as exc:  # pragma: no cover - operational script
        db.rollback()
        logger.error("Failed to queue test email: %s", exc)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
