"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuditHistoryItem, AuditRecordResponse } from "@/types/auditWorkspace";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";
import { normalizeReport } from "@/lib/auditWorkspaceUtils";
import {
  resolveAuditHistoryScores,
  resolveAuditHistoryTargetFields,
} from "@/lib/auditHistoryContract";
import { fetchAuditById, fetchAuditHistory } from "@/services/auditService";
import type { RawAuditHistoryEntry } from "@/types/aiStrategist";

type UseWorkspaceHistoryParams = {
  getAuthHeaders: () => Promise<Record<string, string>>;
  isSignedIn: boolean;
};
export const resolveHistoryTargetFields = resolveAuditHistoryTargetFields;
export const resolveHistoryScores = resolveAuditHistoryScores;

// ---------------------------------------------------------------------------
// Fetch functions (used as queryFn)
// ---------------------------------------------------------------------------

async function fetchHistoryData(
  getAuthHeaders: () => Promise<Record<string, string>>
): Promise<AuditHistoryItem[]> {
  const authHeaders = await getAuthHeaders();
  const payload = await fetchAuditHistory(authHeaders);
  return payload
    .map((entry: RawAuditHistoryEntry) => {
      const fullReport =
        entry.full_report && typeof entry.full_report === "object"
          ? (entry.full_report as Record<string, unknown>)
          : null;
      const targetFields = resolveHistoryTargetFields({ ...entry, full_report: fullReport });
      const resolvedScores = resolveHistoryScores({ ...entry, full_report: fullReport });

      return {
        id: entry.id,
        url: typeof entry.url === "string" ? entry.url : "",
        auditTargetType: targetFields.auditTargetType,
        targetName: targetFields.targetName,
        targetUrl: targetFields.targetUrl,
        targetMetadata: targetFields.targetMetadata,
        geoScore: resolvedScores.geoScore,
        seoScore: resolvedScores.seoScore,
        aeoScore: resolvedScores.aeoScore,
        status: typeof entry.status === "string" ? entry.status : "completed",
        auditType:
          typeof entry.audit_type === "string"
            ? entry.audit_type
            : (fullReport?.metadata as Record<string, unknown> | undefined)?.tier
              ? String((fullReport?.metadata as Record<string, unknown>).tier).toUpperCase()
              : "FAST",
        createdAt: entry.created_at,
        projectId: entry.project_id ?? undefined,
        fullReport,
      };
    })
    .sort(
      (left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime()
    );
}

async function fetchReportData(
  selectedAudit: AuditHistoryItem | null
): Promise<{ report: CanonicalAuditReport | null; meta: AuditHistoryItem; isArchived?: boolean }> {
  if (!selectedAudit) {
    throw new Error("Unable to load the assessment report.");
  }

  const auditStatus = (selectedAudit.status || "").toLowerCase();
  const isArchivedOrPurged = auditStatus === "archived" || auditStatus === "purged";

  if (!selectedAudit.fullReport) {
    if (isArchivedOrPurged) {
      // Archived/purged audits may not have a full_report, return null report with meta
      const meta: AuditHistoryItem = { ...selectedAudit };
      return { report: null, meta, isArchived: true };
    }
    throw new Error("Unable to load the assessment report.");
  }
  const record: AuditRecordResponse = {
    id: selectedAudit.id,
    url: selectedAudit.url,
    audit_target_type: selectedAudit.auditTargetType,
    target_name: selectedAudit.targetName,
    target_url: selectedAudit.targetUrl,
    target_metadata: selectedAudit.targetMetadata,
    geo_score: selectedAudit.geoScore,
    seo_score: selectedAudit.seoScore ?? undefined,
    aeo_score: selectedAudit.aeoScore ?? undefined,
    status: selectedAudit.status,
    audit_type: selectedAudit.auditType,
    created_at: selectedAudit.createdAt,
    full_report: selectedAudit.fullReport,
  };
  const report = normalizeReport(record, record.url);
  const meta: AuditHistoryItem = {
    id: selectedAudit.id,
    url: selectedAudit.url,
    auditTargetType: selectedAudit.auditTargetType,
    targetName: selectedAudit.targetName,
    targetUrl: selectedAudit.targetUrl,
    targetMetadata: selectedAudit.targetMetadata,
    geoScore: selectedAudit.geoScore,
    seoScore: selectedAudit.seoScore,
    aeoScore: selectedAudit.aeoScore,
    status: selectedAudit.status,
    auditType: selectedAudit.auditType,
    createdAt: selectedAudit.createdAt,
    projectId: selectedAudit.projectId,
  };
  return { report, meta };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useWorkspaceHistory({ getAuthHeaders, isSignedIn }: UseWorkspaceHistoryParams) {
  const queryClient = useQueryClient();
  const [selectedAuditId, setSelectedAuditId] = useState<number | null>(null);

  const historyEnabled = isSignedIn;

  // --- History query ---
  const historyQuery = useQuery({
    queryKey: ["audit-history"],
    queryFn: () => fetchHistoryData(getAuthHeaders),
    enabled: historyEnabled,
  });

  // Derive history items (without fullReport for display)
  const rawHistory = useMemo(() => historyQuery.data ?? [], [historyQuery.data]);

  const history = useMemo(() => {
    const displayItems = rawHistory.map(({ fullReport: _fr, ...item }) => item);
    return displayItems;
  }, [rawHistory]);

  const historyForEntitySuggestions = useMemo(() => {
    return rawHistory;
  }, [rawHistory]);

  // Auto-select first on initial load
  useEffect(() => {
    if (!selectedAuditId && history.length > 0) {
      setSelectedAuditId(history[0].id);
    }
  }, [history, selectedAuditId]);

  // --- Report query (driven by selectedAuditId) ---
  const reportQuery = useQuery({
    queryKey: ["audit-report", selectedAuditId],
    queryFn: async () => {
      if (!selectedAuditId) throw new Error("No assessment selected");

      let selectedAudit = rawHistory.find((item) => item.id === selectedAuditId) ?? null;

      if (!selectedAudit?.fullReport) {
        // Fetch individually if it's missing from the history list or doesn't have the full report payload
        const authHeaders = await getAuthHeaders();
        const remoteRecord = await fetchAuditById(selectedAuditId, authHeaders);
        const targetFields = resolveHistoryTargetFields(remoteRecord);
        const resolvedScores = resolveHistoryScores(remoteRecord);

        selectedAudit = {
          id: remoteRecord.id,
          url: remoteRecord.url || "",
          auditTargetType: targetFields.auditTargetType,
          targetName: targetFields.targetName,
          targetUrl: targetFields.targetUrl,
          targetMetadata: targetFields.targetMetadata,
          geoScore: resolvedScores.geoScore,
          seoScore: resolvedScores.seoScore,
          aeoScore: resolvedScores.aeoScore,
          status: remoteRecord.status ?? "completed",
          auditType: remoteRecord.audit_type ?? "FAST",
          createdAt: remoteRecord.created_at || "",
          projectId: remoteRecord.project_id,
          fullReport: remoteRecord.full_report as Record<string, unknown>,
        };
      }

      return fetchReportData(selectedAudit);
    },
    enabled: !!selectedAuditId && historyQuery.isSuccess,
  });

  const activeReport = reportQuery.data?.report ?? null;
  const activeAuditMeta = reportQuery.data?.meta ?? null;
  const isActiveAuditArchived = reportQuery.data?.isArchived ?? false;

  // Manually set report after audit completion (optimistic)
  const setActiveReport = useCallback(
    (report: CanonicalAuditReport, meta: AuditHistoryItem) => {
      queryClient.setQueryData(["audit-report", meta.id], { report, meta });
    },
    [queryClient]
  );

  const invalidateHistory = useCallback(() => {
    return queryClient.invalidateQueries({ queryKey: ["audit-history"] });
  }, [queryClient]);

  const upsertHistoryEntry = useCallback(
    (entry: AuditHistoryItem) => {
      queryClient.setQueryData<AuditHistoryItem[]>(["audit-history"], (existing = []) => {
        const filtered = existing.filter((item) => item.id !== entry.id);
        return [entry, ...filtered].sort(
          (left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime()
        );
      });
    },
    [queryClient]
  );

  const fetchAuditRecord = useCallback(
    async (auditId: number) => {
      const matched = rawHistory.find((item) => item.id === auditId);
      if (matched?.fullReport) {
        return {
          id: matched.id,
          url: matched.url,
          audit_target_type: matched.auditTargetType,
          target_name: matched.targetName,
          target_url: matched.targetUrl,
          target_metadata: matched.targetMetadata,
          geo_score: matched.geoScore,
          seo_score: matched.seoScore ?? undefined,
          aeo_score: matched.aeoScore ?? undefined,
          status: matched.status,
          audit_type: matched.auditType,
          created_at: matched.createdAt,
          full_report: matched.fullReport,
        } as AuditRecordResponse;
      }

      const authHeaders = await getAuthHeaders();
      const remoteRecord = await fetchAuditById(auditId, authHeaders);
      const remoteStatus = (
        typeof remoteRecord.status === "string" ? remoteRecord.status : ""
      ).toLowerCase();
      if (
        (!remoteRecord.full_report || typeof remoteRecord.full_report !== "object") &&
        remoteStatus !== "archived" &&
        remoteStatus !== "purged"
      ) {
        throw new Error("Unable to load the assessment report.");
      }
      const targetFields = resolveHistoryTargetFields(remoteRecord);

      return {
        id: remoteRecord.id,
        url: remoteRecord.url ?? "",
        audit_target_type: targetFields.auditTargetType,
        target_name: targetFields.targetName,
        target_url: targetFields.targetUrl,
        target_metadata: targetFields.targetMetadata,
        geo_score: typeof remoteRecord.geo_score === "number" ? remoteRecord.geo_score : 0,
        seo_score: typeof remoteRecord.seo_score === "number" ? remoteRecord.seo_score : undefined,
        aeo_score: typeof remoteRecord.aeo_score === "number" ? remoteRecord.aeo_score : undefined,
        status: typeof remoteRecord.status === "string" ? remoteRecord.status : undefined,
        audit_type:
          typeof remoteRecord.audit_type === "string" ? remoteRecord.audit_type : undefined,
        created_at: remoteRecord.created_at ?? "",
        full_report: remoteRecord.full_report as Record<string, unknown>,
      } as AuditRecordResponse;
    },
    [getAuthHeaders, rawHistory]
  );

  const sortedHistory = useMemo(
    () =>
      [...history].sort(
        (left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime()
      ),
    [history]
  );

  const geoTrend = useMemo(() => {
    if (!sortedHistory.length) return [];
    return sortedHistory.slice(0, 6).reverse();
  }, [sortedHistory]);

  return {
    history,
    historyForEntitySuggestions,
    historyLoading: historyQuery.isLoading,
    historyError: historyQuery.error?.message ?? "",
    historyRefetch: historyQuery.refetch,
    selectedAuditId,
    setSelectedAuditId,
    activeReport,
    activeAuditMeta,
    isActiveAuditArchived,
    setActiveReport,
    reportLoading: reportQuery.isLoading,
    reportError: reportQuery.error?.message ?? "",
    fetchAuditRecord,
    invalidateHistory,
    upsertHistoryEntry,
    sortedHistory,
    geoTrend,
  };
}
