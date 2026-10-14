"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/components/auth/custom-auth";
import {
  fetchProjectById,
  fetchProjectLatestAudit,
  fetchProjectLatestAuditSelection,
  type ProjectAuditModule,
  type ProjectAuditHistoryEntry,
  type ProjectDetails,
  type ProjectLatestAuditSelection,
} from "@/services/workspaceService";

type UseProjectLatestAuditOptions = {
  module?: ProjectAuditModule;
  preferredAuditType?: "STANDARD" | "DEEP";
  includeFullReport?: boolean;
};

type UseProjectLatestAuditResult = {
  project: ProjectDetails | null;
  latestAudit: ProjectAuditHistoryEntry | null;
  auditSelection: ProjectLatestAuditSelection | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
};

export function useProjectLatestAudit(
  projectId: string,
  options: UseProjectLatestAuditOptions = {}
): UseProjectLatestAuditResult {
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();
  const [project, setProject] = useState<ProjectDetails | null>(null);
  const [latestAudit, setLatestAudit] = useState<ProjectAuditHistoryEntry | null>(null);
  const [auditSelection, setAuditSelection] = useState<ProjectLatestAuditSelection | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const requestGenerationRef = useRef(0);

  const auditModule = options.module;
  const preferredAuditType = options.preferredAuditType;
  const includeFullReport = options.includeFullReport ?? true;

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to load project assessment data.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const load = useCallback(async () => {
    const requestGeneration = ++requestGenerationRef.current;
    const isCurrentRequest = () => requestGenerationRef.current === requestGeneration;

    if (!projectId || authLoading) {
      return;
    }
    if (!isSignedIn) {
      if (!isCurrentRequest()) return;
      setProject(null);
      setLatestAudit(null);
      setAuditSelection(null);
      setLoading(false);
      setError("Sign in to access project intelligence modules.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();

      if (auditModule) {
        const [projectPayload, selectionPayload] = await Promise.all([
          fetchProjectById(projectId, headers),
          fetchProjectLatestAuditSelection(projectId, headers, {
            includeFullReport,
            module: auditModule,
          }),
        ]);
        if (!isCurrentRequest()) return;
        setProject(projectPayload);
        setAuditSelection(selectionPayload);
        setLatestAudit(selectionPayload.selected_audit);
        return;
      }

      const [projectPayload, preferredLatestAudit] = await Promise.all([
        fetchProjectById(projectId, headers),
        fetchProjectLatestAudit(projectId, headers, {
          includeFullReport,
          auditType: preferredAuditType,
        }),
      ]);
      if (!isCurrentRequest()) return;

      let resolvedLatestAudit = preferredLatestAudit;
      if (!resolvedLatestAudit && preferredAuditType) {
        resolvedLatestAudit = await fetchProjectLatestAudit(projectId, headers, {
          includeFullReport,
        });
        if (!isCurrentRequest()) return;
      }

      setProject(projectPayload);
      setAuditSelection(null);
      setLatestAudit(resolvedLatestAudit);
    } catch (loadError) {
      if (!isCurrentRequest()) return;
      setProject(null);
      setLatestAudit(null);
      setAuditSelection(null);
      setError(
        loadError instanceof Error ? loadError.message : "Unable to load project assessment data."
      );
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [
    authLoading,
    getAuthHeaders,
    includeFullReport,
    isSignedIn,
    auditModule,
    preferredAuditType,
    projectId,
  ]);

  useEffect(() => {
    void load();
    return () => {
      requestGenerationRef.current += 1;
    };
  }, [load]);

  return useMemo(
    () => ({
      project,
      latestAudit,
      auditSelection,
      loading,
      error,
      refetch: load,
    }),
    [auditSelection, error, latestAudit, load, loading, project]
  );
}
