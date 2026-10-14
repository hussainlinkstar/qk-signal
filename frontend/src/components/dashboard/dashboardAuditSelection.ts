import type { AuditResult } from "../../types/auditResult";
import {
  type AuditHistoryPayload,
  filterScoreableAuditHistory,
  normalizeAuditHistoryPayload,
} from "../../lib/dashboardHistoryAdapters";

export type { AuditHistoryPayload };

export const selectLatestDashboardAudit = (payload: AuditHistoryPayload[]): AuditResult | null => {
  const normalizedHistory = normalizeAuditHistoryPayload(payload);
  if (normalizedHistory.length === 0) {
    return null;
  }

  const scoreableHistory = filterScoreableAuditHistory(normalizedHistory);
  const preferredHistory = scoreableHistory.length > 0 ? scoreableHistory : normalizedHistory;

  return preferredHistory[preferredHistory.length - 1] ?? null;
};
