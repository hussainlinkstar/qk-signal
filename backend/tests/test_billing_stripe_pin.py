"""Guard the pinned stripe-python against a silent breaking upgrade.

The immediate plan-change proration preview in ``billing/router.py`` calls
``stripe.Invoice.upcoming(...)``. That method backs ``GET /v1/invoices/upcoming``,
which Stripe removed in API version ``2025-03-31.basil`` and stripe-python
removed in ``12.0.0``. Every existing preview test patches the whole ``stripe``
module, so a ``MagicMock`` satisfies ``Invoice.upcoming`` whatever is installed:
a future bump to ``stripe>=12`` would go green in CI and break every immediate
plan change at a customer's checkout.

These assertions run against the REAL installed library, deliberately not a
mock. If this test fails during a dependency bump, do not delete it: migrate
the preview to the Create Preview Invoice API
(``POST /v1/invoices/create_preview`` / ``stripe.Invoice.create_preview``)
first, then relax the assertions.
"""

import stripe


def test_invoice_upcoming_exists_in_installed_stripe():
    assert hasattr(stripe.Invoice, "upcoming"), (
        f"stripe {stripe.VERSION} no longer exposes Invoice.upcoming - it was "
        "removed in stripe-python 12.x together with the underlying "
        "GET /v1/invoices/upcoming endpoint (Stripe API 2025-03-31.basil). "
        "Do not delete this assertion: migrate the plan-change preview in "
        "billing/router.py to the Create Preview Invoice API "
        "(stripe.Invoice.create_preview) first."
    )


def test_installed_stripe_major_still_supports_upcoming():
    major = int(str(stripe.VERSION).split(".", 1)[0])
    assert major < 12, (
        f"stripe {stripe.VERSION} is installed but Invoice.upcoming was "
        "removed in stripe-python 12.0.0 and GET /v1/invoices/upcoming was "
        "removed in Stripe API 2025-03-31.basil. Do not delete this "
        "assertion: migrate the plan-change preview in billing/router.py to "
        "the Create Preview Invoice API (stripe.Invoice.create_preview) "
        "before bumping the pin."
    )
