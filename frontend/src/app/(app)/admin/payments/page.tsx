"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Download,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Shield,
  Activity,
  Scale,
  AlertTriangle,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ClientSafeDate } from "@/lib/dateFormat";
import Button from "@/components/ui/Button";
import { PLAN_DISPLAY_NAMES, resolvePlanType } from "@/lib/planCapabilities";

type AdminBillingInvoice = {
  id: number;
  // SIGV2-1144: an invoice outlives the account it was issued to. A customer
  // who deletes their account leaves the invoice behind with no user row, so
  // these can be null and the row reports the recipient identity the invoice
  // itself carries. Reported revenue must not shrink because of an erasure.
  user_id: number | null;
  user_email: string;
  account_deleted?: boolean;
  retention_until?: string | null;
  stripe_invoice_id: string;
  stripe_customer_id: string;
  stripe_subscription_id: string | null;
  amount_paid: number | null;
  amount_due: number | null;
  currency: string | null;
  status: string | null;
  hosted_invoice_url: string | null;
  invoice_pdf: string | null;
  created_at: string;
  plan_type: string | null;
};

type AdminBillingInvoicesResponse = {
  invoices: AdminBillingInvoice[];
  page: number;
  page_size: number;
  total: number;
};

type InvoiceFilters = {
  userEmail: string;
  status: string;
  plan: string;
  startDate: string;
  endDate: string;
  stripeInvoiceId: string;
  stripeCustomerId: string;
  stripeSubscriptionId: string;
};

const defaultFilters: InvoiceFilters = {
  userEmail: "",
  status: "",
  plan: "",
  startDate: "",
  endDate: "",
  stripeInvoiceId: "",
  stripeCustomerId: "",
  stripeSubscriptionId: "",
};

const MICRO_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md border px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const CHIP_NEUTRAL = `${CHIP} border-(--line) bg-(--line-2) text-(--t-2)`;
const CHIP_GOOD = `${CHIP} border-transparent text-(--good) bg-(--good-s)`;
const PAGER_BUTTON =
  "inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-[13px] font-medium text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40";

const formatAmount = (amount: number | null, currency: string | null) => {
  if (amount === null || amount === undefined || !currency) {
    return "-";
  }
  const normalizedCurrency = currency.toUpperCase();
  const value = amount / 100;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: normalizedCurrency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch (error) {
    return `${value.toFixed(2)} ${normalizedCurrency}`;
  }
};

const formatPlanLabel = (plan: string | null) => {
  const canonicalPlan = resolvePlanType(plan);
  return canonicalPlan ? PLAN_DISPLAY_NAMES[canonicalPlan] : plan || "Starter";
};

export default function AdminPaymentsPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [filters, setFilters] = useState<InvoiceFilters>(defaultFilters);
  const [appliedFilters, setAppliedFilters] = useState<InvoiceFilters>(defaultFilters);
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const [data, setData] = useState<AdminBillingInvoicesResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin billing.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const buildDateParam = (value: string, isEnd: boolean) => {
    if (!value) {
      return "";
    }
    const dateValue = isEnd ? `${value}T23:59:59` : `${value}T00:00:00`;
    return new Date(dateValue).toISOString();
  };

  const loadInvoices = useCallback(async () => {
    if (!isSignedIn) {
      return;
    }
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (appliedFilters.startDate) {
        params.set("start_date", buildDateParam(appliedFilters.startDate, false));
      }
      if (appliedFilters.endDate) {
        params.set("end_date", buildDateParam(appliedFilters.endDate, true));
      }
      if (appliedFilters.status) {
        params.set("status", appliedFilters.status);
      }
      if (appliedFilters.plan) {
        params.set("plan", appliedFilters.plan);
      }
      if (appliedFilters.userEmail) {
        params.set("user_email", appliedFilters.userEmail);
      }
      if (appliedFilters.stripeInvoiceId) {
        params.set("stripe_invoice_id", appliedFilters.stripeInvoiceId);
      }
      if (appliedFilters.stripeCustomerId) {
        params.set("stripe_customer_id", appliedFilters.stripeCustomerId);
      }
      if (appliedFilters.stripeSubscriptionId) {
        params.set("stripe_subscription_id", appliedFilters.stripeSubscriptionId);
      }

      const response = await fetch(`/api/admin/billing/invoices?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load invoices.");
      }
      const payload = (await response.json()) as AdminBillingInvoicesResponse;
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load invoices.");
    } finally {
      setIsLoading(false);
    }
  }, [appliedFilters, getAuthHeaders, isSignedIn, page, pageSize]);

  useEffect(() => {
    loadInvoices();
  }, [loadInvoices]);

  const totalPages = useMemo(() => {
    if (!data) {
      return 1;
    }
    return Math.max(1, Math.ceil(data.total / data.page_size));
  }, [data]);

  const controlsDisabled = !isAdmin || isGuardLoading || isLoading;

  const applyFilters = () => {
    setAppliedFilters(filters);
    setPage(1);
  };

  const clearFilters = () => {
    setFilters(defaultFilters);
    setAppliedFilters(defaultFilters);
    setPage(1);
  };

  const columns: SignalDataTableColumn<AdminBillingInvoice>[] = [
    {
      key: "date",
      header: "Payment date",
      sortable: true,
      sortValue: (invoice) => invoice.created_at,
      renderCell: (invoice) => (
        <span className="whitespace-nowrap text-(--t-2)">
          <ClientSafeDate date={invoice.created_at} />
        </span>
      ),
    },
    {
      key: "user",
      header: "User",
      sortable: true,
      sortValue: (invoice) => invoice.user_email,
      renderCell: (invoice) => (
        <>
          <div className="font-semibold text-(--t-1)">{invoice.user_email}</div>
          <div className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--t-3)">
            {invoice.user_id === null
              ? "Account deleted, invoice retained"
              : `UID: ${invoice.user_id}`}
          </div>
        </>
      ),
    },
    {
      key: "plan",
      header: "Subscription plan",
      renderCell: (invoice) => (
        <span className={CHIP_NEUTRAL}>{formatPlanLabel(invoice.plan_type)}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortValue: (invoice) => invoice.status ?? "",
      renderCell: (invoice) => (
        <span className={invoice.status === "paid" ? CHIP_GOOD : CHIP_NEUTRAL}>
          {invoice.status === "paid" ? <Shield size={10} /> : <Activity size={10} />}
          {invoice.status}
        </span>
      ),
    },
    {
      key: "amount",
      header: "Amount",
      sortable: true,
      sortValue: (invoice) => invoice.amount_paid ?? 0,
      renderCell: (invoice) => (
        <>
          <div className="font-semibold text-(--t-1)">
            {formatAmount(invoice.amount_paid, invoice.currency)}
          </div>
          {invoice.amount_due && invoice.amount_due > 0 ? (
            <div className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--warn)">
              Due: {formatAmount(invoice.amount_due, invoice.currency)}
            </div>
          ) : null}
        </>
      ),
    },
    {
      key: "documents",
      header: "Documents",
      align: "right",
      renderCell: (invoice) => (
        <div className="flex justify-end gap-2">
          {invoice.hosted_invoice_url ? (
            <a
              href={invoice.hosted_invoice_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-[#EEF1F6] text-(--t-2) transition-colors hover:border-(--purple) hover:text-(--purple)"
              title="View Invoice"
            >
              <ExternalLink size={14} />
            </a>
          ) : null}
          {invoice.invoice_pdf ? (
            <a
              href={invoice.invoice_pdf}
              target="_blank"
              rel="noopener noreferrer"
              className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-[#EEF1F6] text-(--t-2) transition-colors hover:border-(--purple) hover:text-(--purple)"
              title="Download PDF"
            >
              <Download size={14} />
            </a>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <>
      <DashboardPageIntro icon={Scale} title="Payment history">
        Monitor all financial transactions and invoices across the platform. Access restricted to
        Financial Administrators.
      </DashboardPageIntro>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <section className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[320px] flex-1">
            <label className={MICRO_LABEL}>User search</label>
            <input
              value={filters.userEmail}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, userEmail: event.target.value }))
              }
              className={WINPUT}
              placeholder="Search by user email..."
            />
          </div>

          <div className="w-[180px]">
            <label className={MICRO_LABEL}>Status filter</label>
            <NativeSelect
              variant="auth"
              value={filters.status}
              onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
            >
              <option value="">Any status</option>
              <option value="paid">Paid</option>
              <option value="open">Open</option>
              <option value="draft">Draft</option>
              <option value="void">Void</option>
              <option value="uncollectible">Uncollectible</option>
            </NativeSelect>
          </div>

          <div className="flex gap-2">
            <Button variant="primary" size="md" onClick={applyFilters} disabled={controlsDisabled}>
              Apply filters
            </Button>
            <Button variant="ghost" size="md" onClick={clearFilters} disabled={controlsDisabled}>
              Reset
            </Button>
          </div>
        </div>
      </section>

      <SignalDataTable
        columns={columns}
        rows={data?.invoices ?? []}
        rowKey={(invoice) => invoice.id}
        pageSize={pageSize}
        metaLabel={`${data?.invoices?.length ?? 0} of ${data?.total ?? 0} records`}
        emptyLabel={isLoading ? "Loading payments..." : "No payments found."}
        footer={
          <>
            <nav className="inline-flex items-center gap-1" aria-label="Pagination">
              <button
                type="button"
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                disabled={page <= 1 || controlsDisabled}
                aria-label="Previous page"
                className={PAGER_BUTTON}
              >
                <ChevronLeft size={14} />
              </button>
              <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
                {page} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                disabled={page >= totalPages || controlsDisabled}
                aria-label="Next page"
                className={PAGER_BUTTON}
              >
                <ChevronRight size={14} />
              </button>
            </nav>
            <span className="ms-auto font-(family-name:--mono) text-[11px] text-(--t-3)">
              page {page}
            </span>
          </>
        }
      />
    </>
  );
}
