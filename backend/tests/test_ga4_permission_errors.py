"""SIGV2-1202: a GA4 401 and a GA4 403 are different facts.

Collapsing them into one "access was revoked" instruction is what produced the
reconnect loop: a customer who had already switched Google accounts was told
to reconnect, every time, because a property denial (403) was reported as a
revoked authorization (401).

These tests pin the two halves of the fix in the reporting service: the HTTP
status survives on the raised error, and the reason is classified into a fixed
vocabulary (no provider text, so no account identifier can leak out).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

from app.services.geo.ga4_reporting_service import (  # noqa: E402
    GA4_REASON_INSUFFICIENT_SCOPE,
    GA4_REASON_INVALID_CREDENTIALS,
    GA4_REASON_PERMISSION_DENIED,
    GA4_REASON_PROPERTY_DENIED,
    GA4PermissionError,
    GA4ReportingService,
)


def _service_raising(monkeypatch, status: int, payload: dict | None, text: str = ""):
    import httpx

    class _Resp:
        status_code = status
        content = b"x"

        def __init__(self) -> None:
            self.text = text

        def json(self):
            if payload is None:
                raise ValueError("no json")
            return payload

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    return GA4ReportingService(access_token="tok")


def test_401_is_invalid_credentials(monkeypatch) -> None:
    service = _service_raising(
        monkeypatch,
        401,
        {
            "error": {
                "code": 401,
                "message": "Request had invalid authentication credentials.",
                "status": "UNAUTHENTICATED",
            }
        },
    )
    with pytest.raises(GA4PermissionError) as excinfo:
        service._get("https://example.test/x")
    assert excinfo.value.status_code == 401
    assert excinfo.value.reason == GA4_REASON_INVALID_CREDENTIALS


def test_403_property_denial_is_not_a_revoked_authorization(monkeypatch) -> None:
    service = _service_raising(
        monkeypatch,
        403,
        {
            "error": {
                "code": 403,
                "message": (
                    "User does not have sufficient permissions for this property. "
                    "To learn more about Property ID, see the documentation."
                ),
                "status": "PERMISSION_DENIED",
            }
        },
    )
    with pytest.raises(GA4PermissionError) as excinfo:
        service._get("https://example.test/x")
    assert excinfo.value.status_code == 403
    assert excinfo.value.reason == GA4_REASON_PROPERTY_DENIED


def test_403_missing_scope_is_distinguished_from_a_property_denial(monkeypatch) -> None:
    service = _service_raising(
        monkeypatch,
        403,
        {
            "error": {
                "code": 403,
                "message": "Request had insufficient authentication scopes.",
                "status": "PERMISSION_DENIED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
                    }
                ],
            }
        },
    )
    with pytest.raises(GA4PermissionError) as excinfo:
        service._get("https://example.test/x")
    assert excinfo.value.status_code == 403
    assert excinfo.value.reason == GA4_REASON_INSUFFICIENT_SCOPE


def test_unclassifiable_403_does_not_claim_a_property_denial(monkeypatch) -> None:
    service = _service_raising(monkeypatch, 403, None, text="")
    with pytest.raises(GA4PermissionError) as excinfo:
        service._get("https://example.test/x")
    assert excinfo.value.status_code == 403
    assert excinfo.value.reason == GA4_REASON_PERMISSION_DENIED


def test_error_message_carries_no_provider_text(monkeypatch) -> None:
    # The classifier reads the provider body, but only a fixed reason code
    # leaves the service: an account email in Google's message must not end up
    # in a raised error, a log line or last_error.
    service = _service_raising(
        monkeypatch,
        403,
        {
            "error": {
                "code": 403,
                "message": "User person@example.com does not have sufficient permissions.",
                "status": "PERMISSION_DENIED",
            }
        },
    )
    with pytest.raises(GA4PermissionError) as excinfo:
        service._get("https://example.test/x")
    assert "person@example.com" not in str(excinfo.value)
