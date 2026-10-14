"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/custom-auth";
import type { BillingInterval, BillingOverviewResponse, BillingPlanId } from "@/types/billing";

type BillingActionErrorDetail = {
  code?: string;
  message?: string;
  route?: string;
};

function getBillingActionErrorDetail(payload: unknown): BillingActionErrorDetail | null {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return null;
  }
  const detail = payload.detail;
  if (!detail || typeof detail !== "object") {
    return typeof detail === "string" ? { message: detail } : null;
  }
  const record = detail as Record<string, unknown>;
  return {
    code: typeof record.code === "string" ? record.code : undefined,
    message: typeof record.message === "string" ? record.message : undefined,
    route: typeof record.route === "string" ? record.route : undefined,
  };
}

export function useBillingSettings() {
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const [billingOverview, setBillingOverview] = useState<BillingOverviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const loadBillingOverview = useCallback(async () => {
    if (authLoading || !isSignedIn) {
      if (!authLoading) {
        setIsLoading(false);
      }
      return;
    }

    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/billing/plans", { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load billing details.");
      }
      setBillingOverview((await response.json()) as BillingOverviewResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load billing details.");
    } finally {
      setIsLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn]);

  useEffect(() => {
    void loadBillingOverview();
  }, [loadBillingOverview]);

  const openPortal = useCallback(
    async (clearExistingError: boolean) => {
      if (clearExistingError) {
        setActionError("");
      }
      setActionLoading("portal");
      try {
        const headers = await getAuthHeaders();
        const response = await fetch("/api/billing/portal-session", {
          method: "POST",
          headers,
        });
        if (!response.ok) {
          const payload: unknown = await response.json().catch(() => null);
          const detail = getBillingActionErrorDetail(payload);
          throw new Error(detail?.message ?? "Unable to open the billing portal.");
        }
        const payload = (await response.json()) as { url?: string };
        if (!payload.url) {
          throw new Error("Stripe portal URL missing from response.");
        }
        window.location.assign(payload.url);
      } catch (err) {
        setActionError(
          err instanceof Error ? err.message : "Unable to redirect to the billing portal."
        );
        setActionLoading(null);
      }
    },
    [getAuthHeaders]
  );

  const handlePortal = useCallback(async () => {
    await openPortal(true);
  }, [openPortal]);

  const handleCheckout = useCallback(
    async (planId: BillingPlanId, billingInterval: BillingInterval = "month") => {
      setActionError("");
      setActionLoading(planId);
      try {
        const headers = await getAuthHeaders();
        const response = await fetch("/api/billing/checkout-session", {
          method: "POST",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ plan: planId, billing_interval: billingInterval }),
        });
        if (!response.ok) {
          const payload: unknown = await response.json().catch(() => null);
          const detail = getBillingActionErrorDetail(payload);
          const message = detail?.message ?? "Unable to start checkout.";
          if (response.status === 409 && detail?.code === "base_subscription_checkout_conflict") {
            setActionError(message);
            setActionLoading(null);
            if (detail.route === "/billing/upgrade") {
              await loadBillingOverview();
              router.push("/dashboard/billing?section=plans");
              return;
            }
            if (detail.route === "/billing/portal-session") {
              await openPortal(false);
              return;
            }
          }
          throw new Error(message);
        }
        const payload = (await response.json()) as { url?: string };
        if (!payload.url) {
          throw new Error("Stripe checkout URL missing from response.");
        }
        window.location.assign(payload.url);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Unable to redirect to checkout.");
        setActionLoading(null);
      }
    },
    [getAuthHeaders, loadBillingOverview, openPortal, router]
  );

  return {
    getAuthHeaders,
    billingOverview,
    isLoading,
    error,
    actionError,
    actionLoading,
    handleCheckout,
    handlePortal,
    loadBillingOverview,
    setActionError,
  };
}
