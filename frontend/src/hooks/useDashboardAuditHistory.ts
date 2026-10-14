"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/components/auth/custom-auth";
import { useTranslation } from "react-i18next";
import type { AuditResult } from "@/types/auditResult";
import { fetchLegacyAuditHistory, fetchUserProjects } from "@/services/auditService";

export type DashboardAuditHistoryState = {
  audit: AuditResult | null;
  history: AuditResult[];
  isLoading: boolean;
  error: string;
  hasCompletedAudit: boolean;
  hasProjects: boolean;
  selectedProjectId?: number;
};

const initialState: DashboardAuditHistoryState = {
  audit: null,
  history: [],
  isLoading: true,
  error: "",
  hasCompletedAudit: false,
  hasProjects: true,
  selectedProjectId: undefined,
};

export function useDashboardAuditHistory(): DashboardAuditHistoryState {
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const { getToken, isSignedIn } = useAuth();
  const [state, setState] = useState<DashboardAuditHistoryState>(initialState);
  const rawProjectId = searchParams?.get("projectId") ?? searchParams?.get("siteId");
  const parsedProjectId = rawProjectId ? Number(rawProjectId) : Number.NaN;
  const hasSelectedProjectId = Number.isInteger(parsedProjectId) && parsedProjectId > 0;
  const selectedProjectId = hasSelectedProjectId ? parsedProjectId : undefined;

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error(t("dashboard.errors.mustBeSignedIn"));
    }

    return { Authorization: `Bearer ${token}` };
  }, [getToken, t]);

  useEffect(() => {
    const loadLatestAudit = async () => {
      setState({ ...initialState, isLoading: true, selectedProjectId });

      try {
        if (!isSignedIn) {
          setState({
            ...initialState,
            isLoading: false,
            error: t("dashboard.errors.signInRequired"),
          });
          return;
        }

        const headers = await getAuthHeaders();
        const [history, projects] = await Promise.all([
          fetchLegacyAuditHistory(headers, selectedProjectId),
          fetchUserProjects(headers),
        ]);

        const hasProjects = projects.length > 0;

        if (history.length === 0) {
          setState({ ...initialState, isLoading: false, hasProjects, selectedProjectId });
          return;
        }

        setState({
          audit: history[history.length - 1] ?? null,
          history,
          isLoading: false,
          error: "",
          hasCompletedAudit: true,
          hasProjects,
          selectedProjectId,
        });
      } catch (err) {
        setState({
          ...initialState,
          isLoading: false,
          error: err instanceof Error ? err.message : t("dashboard.errors.unableToLoadModuleData"),
          selectedProjectId,
        });
      }
    };

    void loadLatestAudit();
  }, [getAuthHeaders, isSignedIn, selectedProjectId, t]);

  return state;
}
