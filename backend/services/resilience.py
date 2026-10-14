import asyncio
import time
from collections.abc import Callable, Iterable


class ServiceUnavailableError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.opened_until = 0.0

    def allow_request(self) -> bool:
        return time.monotonic() >= self.opened_until

    def is_open(self) -> bool:
        return not self.allow_request()

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_until = 0.0

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_until = time.monotonic() + self.recovery_timeout

    def reset(self) -> None:
        """Force-reset the circuit breaker (useful for test harnesses)."""
        self.failure_count = 0
        self.opened_until = 0.0


async def retry_with_backoff(
    operation,
    breaker: CircuitBreaker,
    service_name: str,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    on_retry=None,
    should_retry: Callable[[Exception], bool] | None = None,
    retryable_exceptions: Iterable[type[Exception]] | None = None,
):
    if should_retry is None and retryable_exceptions is not None:
        retryable_tuple = tuple(retryable_exceptions)

        def should_retry(exc: Exception) -> bool:
            return isinstance(exc, retryable_tuple)

    if not breaker.allow_request():
        raise ServiceUnavailableError(
            f"{service_name} service temporarily unavailable due to repeated failures."
        )

    attempt = 0
    while True:
        if not breaker.allow_request():
            raise ServiceUnavailableError(
                f"{service_name} service temporarily unavailable due to repeated failures."
            )
        try:
            result = await operation()
            breaker.record_success()
            return result
        except Exception as exc:
            if should_retry is not None and not should_retry(exc):
                raise

            breaker.record_failure()
            if breaker.is_open():
                raise ServiceUnavailableError(
                    f"{service_name} service temporarily unavailable due to repeated failures."
                )
            if attempt >= retries:
                raise
            delay = min(max_delay, base_delay * (2**attempt))
            if on_retry:
                on_retry(exc, attempt + 1, delay)
            attempt += 1
            await asyncio.sleep(delay)
