import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.observability import (
    ERROR_CODE_HTTP_ERROR,
    ERROR_CODE_QUOTA_EXHAUSTED,
    classify_error_code,
    is_retryable,
)


def test_classify_error_code_marks_quota_exhausted_for_insufficient_quota_message() -> None:
    error_code = classify_error_code(
        message="429 insufficient_quota: You exceeded your current quota",
        status_code=429,
    )

    assert error_code == ERROR_CODE_QUOTA_EXHAUSTED
    assert is_retryable(error_code) is False


def test_classify_error_code_marks_quota_exhausted_for_billing_hard_limit_message() -> None:
    error_code = classify_error_code(
        message="Billing hard limit has been reached",
        status_code=429,
    )

    assert error_code == ERROR_CODE_QUOTA_EXHAUSTED


def test_classify_error_code_marks_quota_exhausted_for_firecrawl_payment_required_message() -> None:
    # Real Firecrawl 402 error text as raised by the SDK (message-only, no
    # structured status_code available to the caller, mirroring how
    # ScraperService._classify_error_code invokes this). Retrying is pointless
    # until the account is recharged, so it must be classified as non-retryable
    # instead of falling through to the generic retryable default.
    error_code = classify_error_code(
        message=(
            "Payment Required: Failed to scrape. Insufficient credits to perform "
            "this request. For more credits, you can upgrade your plan at "
            "https://firecrawl.dev/pricing"
        ),
    )

    assert error_code == ERROR_CODE_QUOTA_EXHAUSTED
    assert is_retryable(error_code) is False


def test_classify_error_code_keeps_non_quota_http_client_errors_non_retryable() -> None:
    error_code = classify_error_code(message="invalid request", status_code=400)

    assert error_code == ERROR_CODE_HTTP_ERROR
    assert is_retryable(error_code) is False


def test_classify_error_code_prefers_structured_error_code_over_message_markers() -> None:
    error_code = classify_error_code(
        error_code=ERROR_CODE_HTTP_ERROR,
        message="timeout while processing request",
        status_code=400,
    )

    assert error_code == ERROR_CODE_HTTP_ERROR
