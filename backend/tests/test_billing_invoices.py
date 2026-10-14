import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import stripe
from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

from billing.router import list_invoices


def _invoice(**overrides):
    values = {
        "id": "in_123",
        "amount_due": 14900,
        "amount_paid": 14900,
        "amount_remaining": 0,
        "currency": "usd",
        "status": "paid",
        "hosted_invoice_url": "https://invoice.stripe.test/in_123",
        "invoice_pdf": "https://invoice.stripe.test/in_123.pdf",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _list_invoices(monkeypatch: pytest.MonkeyPatch, invoices: list[SimpleNamespace]):
    user = SimpleNamespace(
        subscription=SimpleNamespace(stripe_customer_id="cus_123", stripe_mode="test"),
    )
    monkeypatch.setattr("billing.router.require_not_portal_only", lambda _user, detail: None)
    monkeypatch.setattr("billing.router.get_billing_config", lambda _request, _db=None: None)
    monkeypatch.setattr("billing.router._api_key_for_mode", lambda _config, _mode: "test-api-key")
    monkeypatch.setattr(
        "billing.router.stripe.Invoice.list",
        lambda **_kwargs: SimpleNamespace(data=invoices, has_more=False),
    )

    return list_invoices(http_request=None, user=user, db=None)


def test_list_invoices_serializes_stripe_timestamp_as_iso_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _list_invoices(monkeypatch, [_invoice(created=1704067200)])

    assert payload["invoices"][0]["date"] == "2024-01-01T00:00:00+00:00"


def test_list_invoices_maps_stripe_failure_to_safe_unavailable_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(
        id=1,
        subscription=SimpleNamespace(stripe_customer_id="cus_123", stripe_mode="test"),
    )
    monkeypatch.setattr("billing.router.require_not_portal_only", lambda _user, detail: None)
    monkeypatch.setattr("billing.router.get_billing_config", lambda _request, _db=None: None)
    monkeypatch.setattr("billing.router._api_key_for_mode", lambda _config, _mode: "test-api-key")
    monkeypatch.setattr(
        "billing.router.stripe.Invoice.list",
        lambda **_kwargs: (_ for _ in ()).throw(stripe.error.APIConnectionError("offline")),
    )

    with pytest.raises(HTTPException) as exc_info:
        list_invoices(http_request=None, user=user, db=None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": "invoice_history_unavailable",
        "message": "Invoice history is temporarily unavailable.",
    }


def test_list_invoices_omits_non_https_navigation_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _list_invoices(
        monkeypatch,
        [
            _invoice(
                hosted_invoice_url="javascript:alert(1)",
                invoice_pdf="http://invoice.stripe.test/in_123.pdf",
            )
        ],
    )

    assert payload["invoices"][0]["hosted_invoice_url"] is None
    assert payload["invoices"][0]["invoice_pdf"] is None


def test_list_invoices_serializes_missing_null_or_invalid_timestamp_as_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _list_invoices(
        monkeypatch,
        [
            _invoice(id="in_missing"),
            _invoice(id="in_null", created=None),
            _invoice(id="in_invalid", created="not-a-timestamp"),
        ],
    )

    assert [invoice["date"] for invoice in payload["invoices"]] == [None, None, None]
