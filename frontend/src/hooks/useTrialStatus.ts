"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth/custom-auth";
import type { TrialStatus } from "@/types/billing";

const EMPTY_TRIAL: TrialStatus = {
  is_trial: false,
  trial_active: false,
  trial_expired: false,
  trial_plan: null,
  trial_started_at: null,
  trial_ends_at: null,
  days_remaining: 0,
  credits_remaining: 0,
  credits_total: 0,
  audits_used: 0,
  audits_total: 0,
  concierge_completed: false,
  limits_reached: false,
  limit_reason: null,
};

export function useTrialStatus() {
  const { getToken, isLoading: authLoading, isSignedIn } = useAuth();
  const [trial, setTrial] = useState<TrialStatus>(EMPTY_TRIAL);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (authLoading || !isSignedIn) {
      if (!authLoading) setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const token = await getToken();
      if (!token) return;
      const response = await fetch("/api/users/me", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) return;
      const data = (await response.json()) as { trial?: TrialStatus | null };
      setTrial(data.trial ?? EMPTY_TRIAL);
    } catch {
      // Silently ignore, trial UI degrades gracefully
    } finally {
      setIsLoading(false);
    }
  }, [authLoading, getToken, isSignedIn]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const showPaywall = trial.is_trial && trial.limits_reached;
  const showConciergeOnboarding =
    trial.is_trial && trial.trial_active && !trial.concierge_completed;

  return {
    trial,
    isLoading,
    refresh,
    showPaywall,
    showConciergeOnboarding,
  };
}
