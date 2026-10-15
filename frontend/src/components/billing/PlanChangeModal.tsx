"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  Loader2,
  Minus,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";

import SignalAlert from "@/components/signal/SignalAlert";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import { cx } from "@/components/ui/utils";
import type { BillingInterval, BillingPlanId } from "@/types/billing";

/* ---------- types ---------- */

type PlanSummary = { id: string; name: string };
type FeatureDiff = { gained: string[]; lost: string[] };
type ScanAdjustment = {
  current_scans_per_month: number;
  target_scans_per_month: number;
};

export type UpgradePreview = {
  direction: "upgrade" | "downgrade" | "interval_change";
  current_billing_interval: BillingInterval;
  target_billing_interval: BillingInterval;
  current_plan: PlanSummary;
  target_plan: PlanSummary;
  proration_amount_usd: number | null;
  immediate_charge: boolean;
  next_billing_date: string | null;
  feature_diff: FeatureDiff;
  scan_adjustment: ScanAdjustment;
};

type PlanChangeModalProps = {
  open: boolean;
  onClose: () => void;
  targetPlanId: BillingPlanId | null;
  targetBillingInterval: BillingInterval;
  getAuthHeaders: () => Promise<Record<string, string>>;
  onSuccess: () => void;
};

/* ---------- helpers ---------- */

const formatUsd = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

const formatDate = (iso: string) => {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
};

const formatBillingInterval = (interval: BillingInterval) =>
  interval === "year" ? "Annual billing" : "Monthly billing";

type BackendErrorDetail = { code: string | null; message: string | null };

type PlanChangeFailure = { message: string; reference: string | null };

const asTrimmedString = (value: unknown) => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

const readBackendErrorDetail = (body: unknown): BackendErrorDetail => {
  const empty: BackendErrorDetail = { code: null, message: null };
  if (!body || typeof body !== "object" || !("detail" in body)) return empty;
  const detail = body.detail;
  if (typeof detail === "string") return { code: null, message: asTrimmedString(detail) };
  if (!detail || typeof detail !== "object") return empty;
  return {
    code: "code" in detail ? asTrimmedString(detail.code) : null,
    message: "message" in detail ? asTrimmedString(detail.message) : null,
  };
};

const describeStatus = (status: number): string | null => {
  if (status === 401) return "Your session has expired. Sign in again and retry the plan change.";
  if (status === 403) return "This account is not allowed to change plans. Please contact support.";
  if (status === 409) return "Your current subscription could not be validated for a plan change.";
  if (status >= 500)
    return "The billing provider did not respond. Your plan has not changed. Please try again shortly.";
  return null;
};

const describeFailure = (status: number, body: unknown, fallback: string): PlanChangeFailure => {
  const detail = readBackendErrorDetail(body);
  return {
    message: detail.message ?? describeStatus(status) ?? fallback,
    reference: detail.code ? `${status} ${detail.code}` : `HTTP ${status}`,
  };
};

const describeThrown = (err: unknown): PlanChangeFailure => ({
  message: err instanceof Error && err.message ? err.message : "Something went wrong.",
  reference: null,
});

/* ---------- component ---------- */

export default function PlanChangeModal({
  open,
  onClose,
  targetPlanId,
  targetBillingInterval,
  getAuthHeaders,
  onSuccess,
}: PlanChangeModalProps) {
  const [preview, setPreview] = useState<UpgradePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<PlanChangeFailure | null>(null);

  /* ---- fetch preview ---- */
  const loadPreview = useCallback(async () => {
    if (!targetPlanId) return;
    setLoading(true);
    setError(null);
    setPreview(null);
    try {
      const headers = await getAuthHeaders();
      const res = await fetch("/api/billing/upgrade-preview", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          target_plan: targetPlanId,
          billing_interval: targetBillingInterval,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(describeFailure(res.status, body, "Unable to load plan change preview."));
        return;
      }
      setPreview((await res.json()) as UpgradePreview);
    } catch (err) {
      setError(describeThrown(err));
    } finally {
      setLoading(false);
    }
  }, [targetPlanId, targetBillingInterval, getAuthHeaders]);

  useEffect(() => {
    if (open && targetPlanId) {
      void loadPreview();
    }
    if (!open) {
      setPreview(null);
      setError(null);
      setExecuting(false);
    }
  }, [open, targetPlanId, loadPreview]);

  /* ---- execute change ---- */
  const handleConfirm = useCallback(async () => {
    if (!targetPlanId) return;
    setExecuting(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const res = await fetch("/api/billing/upgrade", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          target_plan: targetPlanId,
          billing_interval: targetBillingInterval,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(describeFailure(res.status, body, "Plan change failed."));
        return;
      }
      onSuccess();
      onClose();
    } catch (err) {
      setError(describeThrown(err));
    } finally {
      setExecuting(false);
    }
  }, [targetPlanId, targetBillingInterval, getAuthHeaders, onSuccess, onClose]);

  const isUpgrade = preview?.direction === "upgrade";
  const isDowngrade = preview?.direction === "downgrade";
  const isIntervalChange = preview?.direction === "interval_change";
  const isImmediateChange = isUpgrade || isIntervalChange;

  return (
    <Modal open={open} onClose={onClose} panelClassName="max-w-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-(--border) px-6 py-4">
        <div className="flex items-center gap-2">
          {isImmediateChange ? (
            <TrendingUp className="h-5 w-5 text-(--primary)" />
          ) : (
            <TrendingDown className="h-5 w-5 text-amber-400" />
          )}
          <h2 className="text-lg font-semibold text-(--foreground)">
            {loading
              ? "Loading preview..."
              : isIntervalChange
                ? "Change Billing Interval"
                : isUpgrade
                  ? "Upgrade Plan"
                  : "Downgrade Plan"}
          </h2>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-(--muted-foreground) hover:bg-(--surface-subtle) hover:text-(--foreground)"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Body */}
      <div className="space-y-5 px-6 py-5">
        {loading && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <Loader2 className="h-8 w-8 animate-spin text-(--muted-foreground)" />
            <p className="text-sm text-(--muted-foreground)">Calculating proration...</p>
          </div>
        )}

        {/* SIGV2-1171: the same behaviour SIGV2-1172 built here, now in the
            shared presentation rather than this file's own rose-tinted div, so
            a plan-change failure and every other failure in the app read the
            same. The `Reference:` line moved onto `SignalAlert` itself. */}
        {error && (
          <SignalAlert tone="danger" title="Plan change failed" reference={error.reference}>
            {error.message}
          </SignalAlert>
        )}

        {preview && !loading && (
          <>
            {/* Plan transition */}
            <div className="flex items-center justify-center gap-3 rounded-lg bg-(--surface-subtle) p-4">
              <div className="text-center">
                <p className="text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
                  Current
                </p>
                <p className="mt-1 text-sm font-semibold text-(--foreground)">
                  {preview.current_plan.name}
                </p>
                <p className="mt-1 text-xs text-(--muted-foreground)">
                  {formatBillingInterval(preview.current_billing_interval)}
                </p>
              </div>
              <ChevronRight className="h-5 w-5 text-(--muted-foreground)" />
              <div className="text-center">
                <p className="text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
                  New
                </p>
                <p
                  className={cx(
                    "mt-1 text-sm font-semibold",
                    isImmediateChange ? "text-(--primary)" : "text-amber-400"
                  )}
                >
                  {preview.target_plan.name}
                </p>
                <p
                  className={cx(
                    "mt-1 text-xs",
                    isImmediateChange ? "text-(--primary)" : "text-amber-400"
                  )}
                >
                  {formatBillingInterval(preview.target_billing_interval)}
                </p>
              </div>
            </div>

            {/* Scan allowance change */}
            <div className="flex items-center justify-between rounded-lg bg-(--surface-subtle) p-3">
              <span className="text-xs text-(--muted-foreground)">Monthly audits</span>
              <span className="text-sm font-medium text-(--foreground)">
                {preview.scan_adjustment.current_scans_per_month.toLocaleString()}
                {" → "}
                <span className={isImmediateChange ? "text-(--primary)" : "text-amber-400"}>
                  {preview.scan_adjustment.target_scans_per_month.toLocaleString()}
                </span>
              </span>
            </div>

            {/* Proration / billing info */}
            {isImmediateChange && (
              <div className="rounded-[14px] border-0 bg-[#EEF1F6] p-4 space-y-2">
                {preview.proration_amount_usd !== null && (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-(--muted-foreground)">Prorated charge today</span>
                    <span className="text-sm font-semibold text-(--foreground)">
                      {formatUsd(preview.proration_amount_usd)}
                    </span>
                  </div>
                )}
                {preview.next_billing_date && (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-(--muted-foreground)">Next billing date</span>
                    <span className="text-xs text-(--foreground)">
                      {formatDate(preview.next_billing_date)}
                    </span>
                  </div>
                )}
                <p className="text-xs text-(--muted-foreground)">
                  Your plan change takes effect immediately.
                </p>
              </div>
            )}

            {isDowngrade && preview.next_billing_date && (
              <SignalAlert tone="warning" title="This downgrade is not immediate">
                Your current plan features will remain active until{" "}
                <span className="font-semibold text-(--t-1)">
                  {formatDate(preview.next_billing_date)}
                </span>
                . The new plan takes effect at the start of your next billing period.
              </SignalAlert>
            )}

            {/* Feature diff */}
            {(preview.feature_diff.gained.length > 0 || preview.feature_diff.lost.length > 0) && (
              <div className="space-y-3">
                <p className="text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
                  Feature changes
                </p>
                {preview.feature_diff.gained.length > 0 && (
                  <div className="space-y-1.5">
                    {preview.feature_diff.gained.map((feat) => (
                      <div key={feat} className="flex items-center gap-2 text-xs">
                        <Check className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                        <span className="text-(--foreground)">{feat}</span>
                      </div>
                    ))}
                  </div>
                )}
                {preview.feature_diff.lost.length > 0 && (
                  <div className="space-y-1.5">
                    {preview.feature_diff.lost.map((feat) => (
                      <div key={feat} className="flex items-center gap-2 text-xs">
                        <Minus className="h-3.5 w-3.5 text-rose-400 shrink-0" />
                        <span className="text-(--muted-foreground)">{feat}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer */}
      {preview && !loading && (
        <div className="flex items-center justify-end gap-3 border-t border-(--border) px-6 py-4">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={executing}>
            Cancel
          </Button>
          <Button
            variant={isImmediateChange ? "primary" : "outline"}
            size="sm"
            onClick={handleConfirm}
            loading={executing}
            loadingText={isUpgrade ? "Upgrading..." : "Confirming..."}
          >
            {isImmediateChange ? (
              <>
                {isIntervalChange ? "Confirm Interval Change" : "Confirm Upgrade"}
                <ArrowUpRight className="h-3.5 w-3.5" />
              </>
            ) : (
              "Confirm Downgrade"
            )}
          </Button>
        </div>
      )}
    </Modal>
  );
}
