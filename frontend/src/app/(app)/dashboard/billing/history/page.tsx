"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { History, ChevronLeft, CreditCard, Download, ExternalLink, Loader2 } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import Button from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";
import SignalTable, { type SignalTableColumn } from "@/components/signal/SignalTable";
import { formatDate } from "@/lib/dateFormat";
import { cx } from "@/components/ui/utils";
import type { Invoice, InvoiceResponse } from "@/types/billing";

const formatCurrency = (amount: number | null, currency: string | null) => {
  if (amount === null) return "N/A";
  const normalizedCurrency = (currency ?? "usd").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: normalizedCurrency,
    }).format(amount / 100);
  } catch {
    return `${amount / 100} ${normalizedCurrency}`;
  }
};

export default function BillingHistoryPage() {
  const { getToken, isSignedIn } = useAuth();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to view invoices.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadInvoices = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/billing/invoices", { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load invoices.");
      }
      const payload = (await response.json()) as InvoiceResponse;
      setInvoices(payload.invoices ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong while loading invoices.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    if (!isSignedIn) {
      setIsLoading(false);
      setError("Sign in to view invoices.");
      return;
    }
    loadInvoices();
  }, [isSignedIn, loadInvoices]);

  const rows = useMemo(() => invoices, [invoices]);

  const columns: SignalTableColumn<Invoice>[] = [
    {
      key: "date",
      header: "Date",
      renderCell: (invoice) => (
        <span className="font-medium text-(--t-1)">
          {invoice.date ? formatDate(invoice.date) : "N/A"}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      renderCell: (invoice) => (
        <span
          className={cx(
            "inline-flex rounded-full px-2.5 py-1 text-xs uppercase tracking-wide",
            invoice.status === "paid"
              ? "bg-(--good-s) text-(--good)"
              : "bg-(--warn-s) text-(--warn)"
          )}
        >
          {invoice.status}
        </span>
      ),
    },
    {
      key: "paid",
      header: "Paid",
      renderCell: (invoice) => (
        <span className="text-(--t-2)">
          {formatCurrency(invoice.amounts.amount_paid, invoice.currency)}
        </span>
      ),
    },
    {
      key: "due",
      header: "Amount Due",
      renderCell: (invoice) => (
        <span className="text-(--t-3)">
          {formatCurrency(invoice.amounts.amount_due, invoice.currency)}
        </span>
      ),
    },
    {
      key: "download",
      header: "Download",
      align: "right",
      renderCell: (invoice) =>
        invoice.hosted_invoice_url ? (
          <a
            href={invoice.hosted_invoice_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-(--line) bg-(--line-2) text-(--t-2) transition-all hover:border-[color-mix(in_srgb,var(--blue)_20%,transparent)] hover:text-(--blue)"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : invoice.invoice_pdf ? (
          <a
            href={invoice.invoice_pdf}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-(--line) bg-(--line-2) text-(--t-2) transition-all hover:border-[color-mix(in_srgb,var(--blue)_20%,transparent)] hover:text-(--blue)"
          >
            <Download className="h-3.5 w-3.5" />
          </a>
        ) : (
          <span className="text-xs text-(--t-3)">Unavailable</span>
        ),
    },
  ];

  return (
    <div className="dashboard-page-shell group/main space-y-8">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <DashboardPageIntro icon={History} title="Billing History" color="var(--primary)">
          Review past invoices and download receipts for your account.
        </DashboardPageIntro>

        <div className="flex flex-col md:items-end gap-4">
          <div className="flex items-center gap-2 text-xs text-(--t-2)">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            <span>Billing / Invoices</span>
          </div>
          <Link href="/dashboard/billing">
            <Button variant="ghost" size="sm">
              <ChevronLeft className="h-3 w-3 mr-1" /> Back to Billing
            </Button>
          </Link>
        </div>
      </div>

      {/* Invoice Table */}
      <GlassCard className="p-0 overflow-hidden border-(--line) bg-(--line-2) rounded-md">
        <div className="p-6 border-b border-(--line) flex items-center justify-between">
          <h3 className="text-lg font-semibold text-(--t-1) flex items-center gap-3">
            <CreditCard className="h-4 w-4 text-(--t-2)" />
            Invoice History
          </h3>
          {isLoading && <Loader2 className="h-4 w-4 text-(--t-2) animate-spin" />}
        </div>

        {error && (
          <SignalAlert tone="danger" title="Invoices unavailable" className="mx-6 mt-6">
            {error}
          </SignalAlert>
        )}

        <div className="overflow-x-auto px-2 py-2">
          <SignalTable
            columns={columns}
            rows={rows}
            rowKey={(invoice) =>
              invoice.hosted_invoice_url ?? invoice.invoice_pdf ?? invoice.date ?? invoice.status
            }
            emptyLabel={
              isLoading ? "Loading invoices…" : "No invoices yet. Future invoices will appear here."
            }
          />
        </div>
      </GlassCard>
    </div>
  );
}
