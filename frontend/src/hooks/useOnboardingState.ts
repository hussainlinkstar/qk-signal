"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth/custom-auth";

export type OnboardingState = {
  completed_steps: string[];
  started_at: string | null;
  dismissed_at: string | null;
  updated_at: string | null;
};

export type UpdateOnboardingPayload = {
  completed_steps?: string[];
  add_completed_steps?: string[];
  started?: boolean;
  dismissed?: boolean;
};

const EMPTY_ONBOARDING_STATE: OnboardingState = {
  completed_steps: [],
  started_at: null,
  dismissed_at: null,
  updated_at: null,
};

export function useOnboardingState() {
  const { getToken, isLoading: authLoading, isSignedIn } = useAuth();
  const [state, setState] = useState<OnboardingState>(EMPTY_ONBOARDING_STATE);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchState = useCallback(async () => {
    if (authLoading || !isSignedIn) {
      if (!authLoading) {
        setIsLoading(false);
      }
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) {
        throw new Error("Unable to load onboarding state.");
      }
      const response = await fetch("/api/users/me/onboarding", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? "Unable to load onboarding state.");
      }
      const payload = (await response.json()) as OnboardingState;
      setState({
        completed_steps: Array.isArray(payload.completed_steps) ? payload.completed_steps : [],
        started_at: payload.started_at ?? null,
        dismissed_at: payload.dismissed_at ?? null,
        updated_at: payload.updated_at ?? null,
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load onboarding state.");
    } finally {
      setIsLoading(false);
    }
  }, [authLoading, getToken, isSignedIn]);

  const updateState = useCallback(
    async (payload: UpdateOnboardingPayload) => {
      const token = await getToken();
      if (!token) {
        throw new Error("Unable to update onboarding state.");
      }
      const response = await fetch("/api/users/me/onboarding", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const responsePayload = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(responsePayload?.detail ?? "Unable to update onboarding state.");
      }
      const updated = (await response.json()) as OnboardingState;
      setState({
        completed_steps: Array.isArray(updated.completed_steps) ? updated.completed_steps : [],
        started_at: updated.started_at ?? null,
        dismissed_at: updated.dismissed_at ?? null,
        updated_at: updated.updated_at ?? null,
      });
      return updated;
    },
    [getToken]
  );

  useEffect(() => {
    void fetchState();
  }, [fetchState]);

  return {
    state,
    isLoading,
    error,
    refresh: fetchState,
    updateState,
  };
}
