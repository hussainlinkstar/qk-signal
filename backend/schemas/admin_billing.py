"""Pydantic schemas for admin billing endpoints.

Extracted from admin.py to reduce clutter and centralise billing
request/response contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
#  Subscription
# ---------------------------------------------------------------------------


class AdminBillingSubscriptionEntry(BaseModel):
    id: int
    user_id: int
    user_email: str
    stripe_customer_id: str
    stripe_subscription_id: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    plan_type: str
    status: str


class AdminBillingSubscriptionsResponse(BaseModel):
    subscriptions: list[AdminBillingSubscriptionEntry]


# ---------------------------------------------------------------------------
#  Stripe mode / price config
# ---------------------------------------------------------------------------


class AdminBillingPriceConfigEntry(BaseModel):
    plan: str
    configured: bool
    active_price_id: str | None = None
    test_price_id: str | None = None
    live_price_id: str | None = None


class AdminBillingCommitmentPriceConfigEntry(BaseModel):
    tier: str
    configured: bool
    active_price_id: str | None = None
    test_price_id: str | None = None
    live_price_id: str | None = None


class AdminBillingOveragePriceConfig(BaseModel):
    configured: bool
    active_price_id: str | None = None
    test_price_id: str | None = None
    live_price_id: str | None = None


class AdminBillingModeConfigEntry(BaseModel):
    mode: Literal["test", "live"]
    secret_configured: bool
    webhook_configured: bool
    secret_hint: str | None = None
    webhook_hint: str | None = None


# ---------------------------------------------------------------------------
#  Billing config read / update
# ---------------------------------------------------------------------------


class AdminBillingConfigResponse(BaseModel):
    billing_enabled: bool
    webhook_configured: bool
    stripe_mode: Literal["test", "live"]
    stripe_mode_source: str
    has_runtime_override: bool
    modes: list[AdminBillingModeConfigEntry]
    price_ids: list[AdminBillingPriceConfigEntry]
    commitment_price_ids: list[AdminBillingCommitmentPriceConfigEntry]
    commitment_overage_price_ids: AdminBillingOveragePriceConfig


class AdminBillingConfigUpdateRequest(BaseModel):
    billing_enabled: bool | None = None
    stripe_mode: Literal["test", "live"] | None = None
    test_secret_key: str | None = None
    live_secret_key: str | None = None
    test_webhook_secret: str | None = None
    live_webhook_secret: str | None = None
    test_price_ids: dict[str, str | None] | None = None
    live_price_ids: dict[str, str | None] | None = None
    test_commitment_price_ids: dict[str, str | None] | None = None
    live_commitment_price_ids: dict[str, str | None] | None = None
    test_commitment_overage_price_id: str | None = None
    live_commitment_overage_price_id: str | None = None


# ---------------------------------------------------------------------------
#  Billing overview
# ---------------------------------------------------------------------------


class AdminBillingOverviewResponse(BaseModel):
    stripe_mode: str
    billing_enabled: bool
    stripe_connected: bool
    stripe_error: str | None = None
    total_subscriptions: int
    active_subscriptions: int
    total_invoices: int
    paid_invoices: int
    open_invoices: int
    monthly_recurring_revenue_estimate: float
    latest_invoice_at: str | None = None


# ---------------------------------------------------------------------------
#  Billing sync
# ---------------------------------------------------------------------------


class AdminBillingSyncResponse(BaseModel):
    stripe_mode: str
    subscriptions_processed: int
    invoices_processed: int
    records_skipped: int
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
#  Catalog sync / validate
# ---------------------------------------------------------------------------


class AdminBillingCatalogSyncRequest(BaseModel):
    mode: Literal["test", "live"]
    scope: Literal["plans", "commitments", "all"] = "all"
    dry_run: bool = False


class AdminBillingCatalogValidateRequest(BaseModel):
    mode: Literal["test", "live"]
    scope: Literal["plans", "commitments", "all"] = "all"


class AdminBillingCatalogItemResponse(BaseModel):
    kind: Literal["plan", "plan_annual", "commitment_fixed", "commitment_overage"]
    key: str
    product_id: str | None = None
    price_id: str | None = None
    action: Literal["reused", "created", "warning", "error"]
    message: str | None = None


class AdminBillingCatalogSyncResultResponse(BaseModel):
    items: list[AdminBillingCatalogItemResponse] = Field(default_factory=list)
    plan_price_ids: dict[str, str] = Field(default_factory=dict)
    annual_plan_price_ids: dict[str, str] = Field(default_factory=dict)
    commitment_price_ids: dict[str, str] = Field(default_factory=dict)
    commitment_overage_price_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class AdminBillingCatalogValidationItemResponse(BaseModel):
    kind: Literal["plan", "plan_annual", "commitment_fixed", "commitment_overage"]
    key: str
    configured_price_id: str | None = None
    status: Literal["valid", "unconfigured", "missing", "mismatch"]
    message: str | None = None
    expected: dict[str, object] = Field(default_factory=dict)
    actual: dict[str, object] = Field(default_factory=dict)


class AdminBillingCatalogSyncResponse(BaseModel):
    mode: Literal["test", "live"]
    scope: Literal["plans", "commitments", "all"]
    dry_run: bool
    result: AdminBillingCatalogSyncResultResponse
    config: AdminBillingConfigResponse


class AdminBillingCatalogValidateResponse(BaseModel):
    mode: Literal["test", "live"]
    scope: Literal["plans", "commitments", "all"]
    results: list[AdminBillingCatalogValidationItemResponse] = Field(default_factory=list)
    config: AdminBillingConfigResponse


# ---------------------------------------------------------------------------
#  Commitments
# ---------------------------------------------------------------------------


class AdminBillingCommitmentEntry(BaseModel):
    id: int
    user_id: int
    user_email: str
    tier: str
    committed_credits: int
    monthly_fee_usd: float
    rate_per_credit: float
    status: str
    cancel_at_period_end: bool
    current_cycle_end: datetime | None
    credits_used: int
    overage_credits: int
    usage_pct: float
    pending_tier: str | None = None


class AdminBillingCommitmentsResponse(BaseModel):
    commitments: list[AdminBillingCommitmentEntry]
    page: int
    page_size: int
    total: int


class AdminBillingCommitmentsOverviewResponse(BaseModel):
    total_commitments: int
    active_commitments: int
    pending_cancellations: int
    commitment_mrr_usd: float
    average_usage_pct: float
    total_overage_credits: int


# ---------------------------------------------------------------------------
#  Invoices
# ---------------------------------------------------------------------------


class AdminBillingInvoiceEntry(BaseModel):
    id: int
    # SIGV2-1144: an invoice outlives the account it was issued to. When the
    # customer has deleted their account the row keeps NULL here and reports
    # the recipient identity the invoice itself carries, so revenue is still
    # attributable without a live user row.
    user_id: int | None
    user_email: str
    account_deleted: bool = False
    retention_until: datetime | None = None
    stripe_invoice_id: str
    stripe_customer_id: str
    stripe_subscription_id: str | None
    amount_paid: int | None
    amount_due: int | None
    currency: str | None
    status: str | None
    hosted_invoice_url: str | None
    invoice_pdf: str | None
    created_at: datetime
    plan_type: str | None


class AdminBillingInvoicesResponse(BaseModel):
    invoices: list[AdminBillingInvoiceEntry]
    page: int
    page_size: int
    total: int
