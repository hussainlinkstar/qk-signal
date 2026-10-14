import asyncio
import logging
import os

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

from core.config import settings
from database import SessionLocal
from observability import configure_logging, init_tracing
from services.email_service import EmailService

logger = logging.getLogger("email_outbox_worker")

POLL_INTERVAL_SECONDS = float(os.getenv("EMAIL_OUTBOX_POLL_INTERVAL_SECONDS", "15"))
ACTIVE_POLL_INTERVAL_SECONDS = float(os.getenv("EMAIL_OUTBOX_ACTIVE_POLL_INTERVAL_SECONDS", "2"))


def _resolve_batch_size() -> int:
    try:
        return max(1, int(settings.EMAIL_OUTBOX_BATCH_SIZE or 25))
    except (TypeError, ValueError):
        return 25


async def worker_loop() -> None:
    while True:
        db = SessionLocal()
        try:
            processed = await EmailService(db).process_outbox_batch(limit=_resolve_batch_size())
        except Exception:
            logger.exception("Failed processing email outbox batch")
            processed = 0
        finally:
            db.close()

        await asyncio.sleep(ACTIVE_POLL_INTERVAL_SECONDS if processed else POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    configure_logging()
    init_tracing("email-outbox-worker")
    asyncio.run(worker_loop())
