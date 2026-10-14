"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/custom-auth";
import type { UserSummary } from "@/types/userSummary";

export type ScanAllowance = {
  used: number | null;
  remaining: number | null;
  resetAt: string | null;
};

/** Reads `/api/users/me` once for the plan's scan allowance (SIGV2-1094). */
export function useScanAllowance(): ScanAllowance | null {
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();
  const [allowance, setAllowance] = useState<ScanAllowance | null>(null);

  useEffect(() => {
    if (authLoading || !isSignedIn) {
      return;
    }
    let cancelled = false;
    void (async () => {
      const token = await getToken();
      const response = await fetch("/api/users/me", {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        cache: "no-store",
      });
      if (!response.ok) {
        return;
      }
      const payload = (await response.json()) as UserSummary;
      if (cancelled) {
        return;
      }
      setAllowance({
        used: typeof payload.scans_used === "number" ? payload.scans_used : null,
        remaining:
          typeof payload.scans_remaining === "number" || payload.scans_remaining === null
            ? payload.scans_remaining
            : undefined,
        resetAt: typeof payload.reset_at === "string" ? payload.reset_at : null,
      });
    })().catch(() => {
      /* allowance is informational; never block the page on it */
    });
    return () => {
      cancelled = true;
    };
  }, [authLoading, getToken, isSignedIn]);

  return allowance;
}
