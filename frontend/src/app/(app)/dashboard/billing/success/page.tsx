"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle2 } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalAlert, { type SignalAlertTone } from "@/components/signal/SignalAlert";
import { buttonClasses } from "@/components/ui/Button";
import type { BillingOverviewResponse } from "@/types/billing";

const POLL_INTERVAL_MS = 5000;
const TIMEOUT_MS = 60000;

export default function BillingSuccessPage() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session_id");
  const { getToken, isSignedIn } = useAuth();
  const [activationStatus, setActivationStatus] = useState<
    "checking" | "pending" | "active" | "timeout" | "error"
  >("checking");
  const [activationMessage, setActivationMessage] = useState("Verifying your plan activation...");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("Sign in to verify activation.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  useEffect(() => {
    let isCancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    if (!isSignedIn) {
      setActivationStatus("error");
      setActivationMessage("Sign in to verify your subscription activation.");
      return () => undefined;
    }

    const checkActivation = async () => {
      try {
        const headers = await getAuthHeaders();
        const response = await fetch("/api/billing/plans", { headers });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Unable to check plan activation.");
        }
        const payload = (await response.json()) as BillingOverviewResponse;
        const isActive = payload?.status === "active";
        if (isCancelled) {
          return;
        }
        if (isActive) {
          setActivationStatus("active");
          setActivationMessage("Your subscription is active and ready to use.");
          if (intervalId) {
            clearInterval(intervalId);
          }
          if (timeoutId) {
            clearTimeout(timeoutId);
          }
          return;
        }
        setActivationStatus("pending");
        setActivationMessage("Finalizing activation. This should only take a moment.");
      } catch (err) {
        if (isCancelled) {
          return;
        }
        setActivationStatus("error");
        setActivationMessage(
          err instanceof Error ? err.message : "Unable to check activation status."
        );
        if (intervalId) {
          clearInterval(intervalId);
        }
        if (timeoutId) {
          clearTimeout(timeoutId);
        }
      }
    };

    checkActivation();
    intervalId = setInterval(checkActivation, POLL_INTERVAL_MS);
    timeoutId = setTimeout(() => {
      if (isCancelled) {
        return;
      }
      setActivationStatus("timeout");
      setActivationMessage(
        "Activation is taking longer than expected. Please refresh or contact support."
      );
      if (intervalId) {
        clearInterval(intervalId);
      }
    }, TIMEOUT_MS);

    return () => {
      isCancelled = true;
      if (intervalId) {
        clearInterval(intervalId);
      }
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, [getAuthHeaders, isSignedIn]);

  const activationTone: SignalAlertTone =
    activationStatus === "active"
      ? "success"
      : activationStatus === "error"
        ? "danger"
        : activationStatus === "timeout"
          ? "warning"
          : "info";
  const activationTitle =
    activationStatus === "active"
      ? "Subscription active"
      : activationStatus === "error"
        ? "Activation verification failed"
        : activationStatus === "timeout"
          ? "Activation delayed"
          : "Verifying activation";

  return (
    <div className="dashboard-page-shell space-y-8">
      <div className="space-y-3">
        <DashboardPageIntro
          icon={CheckCircle2}
          title="Billing update successful"
          color="var(--success)"
        >
          Thanks for upgrading. We are confirming your subscription activation now.
        </DashboardPageIntro>
        <SignalAlert tone={activationTone} title={activationTitle}>
          {activationMessage}
        </SignalAlert>
      </div>

      <div className="rounded border-0 bg-(--line-2)  shadow-inner p-6">
        <h2 className="text-xl font-bold text-(--t-1)">What happens next?</h2>
        <p className="text-sm text-(--t-2) mt-2">
          We are syncing your new plan across the dashboard. You can review invoices or manage
          billing any time.
        </p>
        {sessionId ? (
          <p className="text-xs text-(--t-3) mt-4">Checkout session: {sessionId}</p>
        ) : null}
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/dashboard/billing"
            className={buttonClasses({ variant: "primary", size: "md" })}
          >
            Go to billing overview
          </Link>
          <Link
            href="/dashboard/billing/history"
            className={buttonClasses({ variant: "ghost", size: "md" })}
          >
            View invoices
          </Link>
        </div>
      </div>
    </div>
  );
}
