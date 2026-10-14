"use client";

import { useAuth } from "@/components/auth/custom-auth";
import { useCallback, useEffect, useMemo, useState } from "react";

export type AdminUserSummary = {
  id: number;
  email: string;
  role: string;
  credits: number;
  raw_credits?: number;
  included_audits_30d?: number | null;
  remaining_included_audits_30d?: number | null;
  effective_credits?: number;
  credits_unlimited: boolean;
  audits_run_30d: number;
  subscription: {
    plan_type: string;
    status: string;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
  } | null;
};

const STAFF_ROLES = new Set(["admin", "moderator"]);

type AdminGuardState = {
  isAdmin: boolean;
  isStaff: boolean;
  isModerator: boolean;
  isLoading: boolean;
  error: string | null;
  user: AdminUserSummary | null;
};

export const useAdminGuard = (): AdminGuardState => {
  const { getToken, isSignedIn, isLoading: isAuthLoading } = useAuth();
  const [user, setUser] = useState<AdminUserSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access the admin workspace.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  useEffect(() => {
    // Hold the loading state until auth hydration resolves; otherwise a staff
    // user would see the denial screen flash before the session is known.
    if (isAuthLoading) {
      return;
    }
    if (!isSignedIn) {
      setUser(null);
      setIsLoading(false);
      setError(null);
      return;
    }

    const loadUser = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const headers = await getAuthHeaders();
        const response = await fetch("/api/users/me", { headers });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Unable to load user profile.");
        }
        const payload = (await response.json()) as AdminUserSummary;
        setUser(payload);
      } catch (err) {
        setUser(null);
        setError(err instanceof Error ? err.message : "Unable to load user profile.");
      } finally {
        setIsLoading(false);
      }
    };

    loadUser();
  }, [getAuthHeaders, isSignedIn, isAuthLoading]);

  const isAdmin = useMemo(() => user?.role === "admin", [user?.role]);
  const isModerator = useMemo(() => user?.role === "moderator", [user?.role]);
  const isStaff = useMemo(() => STAFF_ROLES.has(user?.role ?? ""), [user?.role]);

  return { isAdmin, isStaff, isModerator, isLoading, error, user };
};
