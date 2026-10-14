import asyncio
import logging

from core.env_bootstrap import bootstrap_environment
from core.redis_client import get_async_redis_client

bootstrap_environment()

from observability import configure_logging, init_tracing
from services.external_webhook_service import (
    EXTERNAL_WEBHOOK_QUEUE_NAME,
    process_external_webhook_job,
)

logger = logging.getLogger(__name__)


async def worker_loop() -> None:
    redis_client = get_async_redis_client()
    logger.info("External webhook worker listening on queue %s", EXTERNAL_WEBHOOK_QUEUE_NAME)
    try:
        while True:
            result = await redis_client.blpop(EXTERNAL_WEBHOOK_QUEUE_NAME, timeout=5)
            if not result:
                continue
            _, job_id = result
            if not job_id:
                continue
            await process_external_webhook_job(job_id)
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    configure_logging()
    init_tracing("external-webhook-worker")
    asyncio.run(worker_loop())
