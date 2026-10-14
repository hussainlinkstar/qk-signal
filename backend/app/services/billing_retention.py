"""Statutory retention of invoice records, and the deletion receipt (SIGV2-1144).

Why this module exists
----------------------
`DELETE /api/v1/users/me` used to delete `billing_payments`, which is the
invoice record: Stripe identifiers, amounts, currency, status, the hosted
invoice and the PDF. Deleting it is not a privacy measure, it is a breach of a
retention duty, and it also made the admin revenue report shrink retroactively.

The entity is UAE. The binding rules:

* `Cabinet Decision No. 74 of 2023`, Executive Regulation of
  `Federal Decree-Law No. 28 of 2022 on Tax Procedures`, Article 3: a Taxable
  Person retains records for **5 years following the Tax Period to which they
  relate**.
* The same Article extends that period: **+4 years** in a dispute with the
  Authority (or until the dispute is finally settled, whichever is later),
  **+4 years** while a Tax Audit is ongoing, **+4 years** where the Authority
  notified an intention to audit before expiry, and **+1 year** from a
  Voluntary Disclosure.
* `Article 78` of the VAT Decree-Law requires keeping all tax invoices issued
  and received.
* `MD No. 243 of 2025` Article 11: electronic invoices, and the data needed to
  validate them, must stay retrievable and reproducible in complete and
  readable form throughout the period.
* GDPR Article 17(3)(b): erasure does not apply where processing is necessary
  to comply with a legal obligation. After the statutory period the personal
  data in those records must be deleted or anonymised, which is what
  `retention_until` and `retention_hold` exist to decide.

So the invoice row survives account deletion and is anonymised instead of
deleted: it keeps everything that makes it reproducible (both Stripe
identifiers, the subscription reference, amounts, currency, status, the hosted
invoice URL, the PDF URL and the invoice date) plus the recipient identity the
tax invoice itself carries, and it loses its foreign key to a living account.

The clock is not an interval from the deletion date. It runs from the end of
the Tax Period the invoice relates to, so it is stored per row as
`retention_until`, and `retention_hold` keeps a row beyond that date for as
long as an audit, a dispute or a Voluntary Disclosure is open.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, update
from sqlalchemy.orm import Session

import models


# ---------------------------------------------------------------------------
# The statutory clock
# ---------------------------------------------------------------------------

#: Cabinet Decision No. 74 of 2023, Article 3: five years following the Tax
#: Period to which the record relates. Expressed in years, not days, because
#: the statute is expressed in years and because the base is a Tax Period end,
#: not the deletion date.
TAX_RECORD_RETENTION_YEARS = 5

#: Article 3 extensions, in years, keyed by the event that triggers them.
RETENTION_EXTENSION_YEARS: dict[str, int] = {
    # Dispute with the Authority: four years, or until the dispute is finally
    # settled, whichever is later.
    "tax_dispute": 4,
    # Tax Audit already under way.
    "tax_audit": 4,
    # The Authority notified an intention to audit before expiry.
    "notified_tax_audit": 4,
    # Voluntary Disclosure: one year from the date it was submitted.
    "voluntary_disclosure": 1,
}

#: The reasons whose extension is measured from the triggering event rather
#: than added to the end of the base retention period.
_EXTENSIONS_MEASURED_FROM_EVENT = frozenset({"voluntary_disclosure"})

RETENTION_BASIS = (
    "UAE Federal Decree-Law 28/2022 on Tax Procedures, "
    "Cabinet Decision 74/2023 Article 3, VAT Decree-Law Article 78"
)

#: Written onto the invoice row in place of the deleted account's identity
#: when the invoice carried no recipient name of its own.
UNNAMED_INVOICE_CUSTOMER = "Deleted account"


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def tax_period_end(moment: datetime) -> datetime:
    """Return the end of the Tax Period the given date falls in.

    UAE VAT Tax Periods are monthly or quarterly depending on the Taxable
    Person. The quarter end is the later of the two for any given date, so
    using it is correct for a quarterly filer and conservative for a monthly
    one. Deriving it instead of storing a filing frequency keeps this a pure
    function of the invoice date.
    """
    moment = _as_utc(moment)
    quarter_end_month = ((moment.month - 1) // 3) * 3 + 3
    first_of_next_month = datetime(
        moment.year + (1 if quarter_end_month == 12 else 0),
        1 if quarter_end_month == 12 else quarter_end_month + 1,
        1,
        tzinfo=timezone.utc,
    )
    return first_of_next_month - relativedelta(microseconds=1)


def retention_until_for_invoice(invoice_created_at: datetime) -> datetime:
    """The earliest date an invoice record may be purged, absent an extension."""
    return tax_period_end(invoice_created_at) + relativedelta(years=TAX_RECORD_RETENTION_YEARS)


def extended_retention_until(
    base_retention_until: datetime,
    reason: str,
    *,
    event_at: datetime | None = None,
    final_settlement_at: datetime | None = None,
) -> datetime:
    """Apply one Article 3 extension to an already computed retention date."""
    if reason not in RETENTION_EXTENSION_YEARS:
        raise ValueError(f"Unknown retention extension reason: {reason!r}")

    base_retention_until = _as_utc(base_retention_until)
    years = RETENTION_EXTENSION_YEARS[reason]

    if reason in _EXTENSIONS_MEASURED_FROM_EVENT:
        if event_at is None:
            raise ValueError(f"{reason!r} requires the date of the triggering event.")
        candidate = _as_utc(event_at) + relativedelta(years=years)
    else:
        candidate = base_retention_until + relativedelta(years=years)

    candidates = [base_retention_until, candidate]
    if final_settlement_at is not None:
        candidates.append(_as_utc(final_settlement_at))
    return max(candidates)


def effective_retention_until(payment: models.BillingPayment) -> datetime:
    """The retention date for a row, derived when it was never stored.

    Rows that predate this change carry no `retention_until`; their date is
    derived from the invoice date on read rather than backfilled, so the
    migration stays additive.
    """
    stored = getattr(payment, "retention_until", None)
    if stored is not None:
        return _as_utc(stored)
    return retention_until_for_invoice(payment.created_at)


def is_retention_expired(payment: models.BillingPayment, *, now: datetime) -> bool:
    """True when the statutory period has run and no extension is open.

    This is the only gate a future purge job may use. A row under
    `retention_hold` is never expired, however old it is: an open audit,
    dispute or Voluntary Disclosure extends the period for as long as it stays
    open, and the closing date is not knowable in advance.
    """
    if getattr(payment, "retention_hold", False):
        return False
    return effective_retention_until(payment) <= _as_utc(now)


# ---------------------------------------------------------------------------
# Anonymising the invoice record
# ---------------------------------------------------------------------------


def invoice_customer_name_for(user: models.User) -> str:
    """The recipient identity a UAE tax invoice has to carry."""
    for candidate in (
        getattr(user, "company_legal_name", None),
        getattr(user, "company_name", None),
    ):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return UNNAMED_INVOICE_CUSTOMER


def invoice_customer_email_for(user: models.User) -> str | None:
    """The address the invoice was issued to, as Stripe rendered it."""
    for candidate in (getattr(user, "billing_email", None), getattr(user, "email", None)):
        if candidate and str(candidate).strip():
            return str(candidate).strip().lower()
    return None


def snapshot_invoice_customer_identity(db: Session, *, user: models.User) -> int:
    """Copy the invoice recipient identity onto the invoice rows themselves.

    Used before the account's own PII is overwritten (the admin GDPR
    anonymisation path). Without it, wiping `company_legal_name` and
    `billing_email` would leave the retained invoices unable to say who they
    were issued to, which is exactly the reproducibility MD 243/2025 Article 11
    requires. Rows that already carry a snapshot are left alone.
    """
    payments = list(
        db.execute(
            select(models.BillingPayment).where(models.BillingPayment.user_id == user.id)
        ).scalars()
    )
    if not payments:
        return 0

    customer_name = invoice_customer_name_for(user)
    customer_email = invoice_customer_email_for(user)
    snapshotted = 0
    for payment in payments:
        if payment.invoice_customer_name and payment.invoice_customer_email:
            continue
        db.execute(
            update(models.BillingPayment)
            .where(models.BillingPayment.id == payment.id)
            .values(
                invoice_customer_name=payment.invoice_customer_name or customer_name,
                invoice_customer_email=payment.invoice_customer_email or customer_email,
                retention_until=effective_retention_until(payment),
            )
            .execution_options(synchronize_session=False)
        )
        snapshotted += 1
    return snapshotted


@dataclass(frozen=True)
class RetainedInvoices:
    """Outcome of severing a deleted account from its invoice records."""

    retained_count: int
    retained_until: datetime | None


def anonymize_billing_payments_for_user(
    db: Session,
    *,
    user: models.User,
    now: datetime,
) -> RetainedInvoices:
    """Sever the account link on a user's invoices instead of deleting them.

    What the row keeps: `stripe_invoice_id`, `stripe_customer_id`,
    `stripe_subscription_id`, `amount_paid`, `amount_due`, `currency`,
    `status`, `hosted_invoice_url`, `invoice_pdf`, `created_at`, and the
    recipient name and address the invoice itself carries. That is the
    complete and readable form Article 11 requires, and it keeps the admin
    revenue report whole.

    What the row loses: its foreign key to a live `users` row. The account id
    stays as `former_user_id`, which is a plain integer with no relationship,
    so the record can be grouped and evidenced without pointing at a living
    customer identity.
    """
    now = _as_utc(now)
    payments = list(
        db.execute(
            select(models.BillingPayment).where(models.BillingPayment.user_id == user.id)
        ).scalars()
    )
    if not payments:
        return RetainedInvoices(retained_count=0, retained_until=None)

    customer_name = invoice_customer_name_for(user)
    customer_email = invoice_customer_email_for(user)

    furthest: datetime | None = None
    for payment in payments:
        retention_until = effective_retention_until(payment)
        furthest = retention_until if furthest is None else max(furthest, retention_until)
        db.execute(
            update(models.BillingPayment)
            .where(models.BillingPayment.id == payment.id)
            .values(
                user_id=None,
                former_user_id=user.id,
                invoice_customer_name=payment.invoice_customer_name or customer_name,
                invoice_customer_email=payment.invoice_customer_email or customer_email,
                retention_until=retention_until,
                anonymized_at=now,
            )
            .execution_options(synchronize_session=False)
        )

    return RetainedInvoices(retained_count=len(payments), retained_until=furthest)


# ---------------------------------------------------------------------------
# The deletion receipt
# ---------------------------------------------------------------------------


def subject_email_fingerprint(email: str) -> str:
    """A SHA-256 of the normalised address, so a request can be evidenced.

    The receipt has to outlive the account, so it must not hold the address in
    the clear. A fingerprint lets a returning data subject or the Authority
    confirm that one specific address was erased, and evidences nothing else.
    """
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _receipt_reference(now: datetime) -> str:
    return f"QSD-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:16]}"


def record_account_deletion_receipt(
    db: Session,
    *,
    user: models.User,
    now: datetime,
    initiated_by: str,
    initiated_by_admin_user_id: int | None = None,
    erased_record_counts: dict[str, int] | None = None,
    retained_invoices: RetainedInvoices,
) -> models.AccountDeletionReceipt:
    """Persist the evidence that a deletion request was honoured.

    The only previous trace was a `logger.info`, and the user's own
    `EmailOutbox` rows were deleted in the same pass, so nothing could show the
    request had been honoured. This is the record the Authority would ask for
    if the retention above were ever questioned, and it is what the account
    settings copy already promises the customer.
    """
    now = _as_utc(now)
    receipt = models.AccountDeletionReceipt(
        reference=_receipt_reference(now),
        former_user_id=user.id,
        subject_email_fingerprint=subject_email_fingerprint(user.email or ""),
        requested_at=now,
        completed_at=now,
        initiated_by=initiated_by,
        initiated_by_admin_user_id=initiated_by_admin_user_id,
        erased_record_counts=dict(erased_record_counts or {}),
        retained_billing_payment_count=retained_invoices.retained_count,
        retained_until=retained_invoices.retained_until,
        retention_basis=RETENTION_BASIS,
    )
    db.add(receipt)
    return receipt
