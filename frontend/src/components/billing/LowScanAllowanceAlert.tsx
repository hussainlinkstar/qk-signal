"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { requestJson } from "@/services/http";
import { cn } from "@/components/ui/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SIGNAL_ALERT_ACTION } from "@/components/signal/SignalAlert";
import { Wallet, X } from "lucide-react";
import type { ScanAllowanceWarning } from "@/types/billing";

const DISMISS_KEY = "low-scan-allowance-alert-dismissed";
const DISMISS_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

type Props = {
  className?: string;
};

export default function LowScanAllowanceAlert({ className }: Props) {
  const [warning, setWarning] = useState<ScanAllowanceWarning | null>(null);
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    // Check dismissal
    try {
      const raw = localStorage.getItem(DISMISS_KEY);
      if (raw) {
        const ts = parseInt(raw, 10);
        if (Date.now() - ts < DISMISS_TTL_MS) return;
      }
    } catch {
      /* noop */
    }

    setDismissed(false);

    requestJson<ScanAllowanceWarning>({
      endpoint: "/api/billing/scan-warning",
      method: "GET",
      errorMessage: "Failed to load scan allowance warning",
    })
      .then((res) => setWarning(res))
      .catch(() => {
        /* silent, don't block dashboard */
      });
  }, []);

  const handleDismiss = useCallback(() => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      /* noop */
    }
  }, []);

  if (dismissed || !warning?.show_warning) return null;

  return (
    <div className={className}>
      {/* shadcn Alert, brand variant: low scans is a pre-emptive notice, not
          an error, so the surface stays neutral (--panel/--line) with the
          --brand accent on the icon and title instead of the old amber. */}
      <Alert variant="brand" className="pe-12">
        <Wallet strokeWidth={2} aria-hidden="true" />
        <AlertTitle>Low on scans.</AlertTitle>
        <AlertDescription className="gap-3">
          <p>
            You have {warning.remaining.toLocaleString()} scans remaining
            {warning.pct_remaining !== null &&
              ` (${warning.pct_remaining}% of your monthly allowance)`}
            .
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/dashboard/billing"
              className={cn(
                SIGNAL_ALERT_ACTION,
                "border-(--ink) bg-(--ink) text-(--panel) hover:border-(--ink)"
              )}
            >
              View Plans
            </Link>
          </div>
        </AlertDescription>
        <button
          type="button"
          aria-label="Dismiss scan allowance alert"
          onClick={handleDismiss}
          className="absolute end-2 top-2 flex h-7 w-7 items-center justify-center rounded-[6px] text-(--t-3) transition-colors duration-150 hover:bg-(--line-2) hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand) max-md:min-h-11 max-md:min-w-11"
        >
          <X className="h-[13px] w-[13px]" aria-hidden="true" />
        </button>
      </Alert>
    </div>
  );
}
