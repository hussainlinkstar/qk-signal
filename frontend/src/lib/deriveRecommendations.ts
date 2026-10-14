import { buildAuditRecordResponse } from "@/lib/projectAuditFeature";
import { normalizeReportWithDiagnostics } from "@/lib/auditWorkspaceUtils";
import {
  getConsolidatedFixes,
  compareConsolidatedFixes,
  type CanonicalAuditReport,
  type ConsolidatedFix,
} from "@/lib/reportAdapters";

/**
 * The project's single consolidated fix list for its latest audit
 * (SIGV2-1193).
 *
 * Every surface that shows one of these fixes, or a count of them, reads this
 * list: the dashboard's top three, the SEO and AIO Improve tabs, the audit
 * report's shortlist and the full action plan. That is the point - two
 * surfaces disagreeing about how many fixes exist is what started this
 * thread.
 *
 * The fixes live in the *normalized* report, not on the raw
 * `full_report.suggestions` array (which is often empty).
 */
export function deriveRecommendations(latestAudit: unknown): ConsolidatedFix[] {
  const report = normalizeLatestAuditReport(latestAudit);
  return report ? getConsolidatedFixes(report) : [];
}

/** The canonical report behind a project's latest audit, or null when the
    audit has no report yet. Shared normalization for recommendations and
    search types so both read the same canonical shape. */
export function normalizeLatestAuditReport(latestAudit: unknown): CanonicalAuditReport | null {
  if (!latestAudit || typeof latestAudit !== "object") return null;
  const audit = latestAudit as { url?: string | null };
  try {
    return normalizeReportWithDiagnostics(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      buildAuditRecordResponse(latestAudit as any),
      audit.url ?? undefined
    ).report;
  } catch {
    return null;
  }
}

/**
 * The one ordering, delegated to `compareConsolidatedFixes` (SIGV2-1193).
 *
 * This used to sort on severity alone, which left rows tied inside a band and
 * let two surfaces order the same band differently. `getConsolidatedFixes`
 * already returns the list in this order, so calling it again is a no-op kept
 * for the call sites that sort a filtered subset.
 */
export function sortRecommendations(recs: ConsolidatedFix[]): ConsolidatedFix[] {
  return [...recs].sort(compareConsolidatedFixes);
}
