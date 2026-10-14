/**
 * Shared helpers for the Audit Library list view.
 * Safely extracts display-ready fields from RawAuditHistoryEntry payloads,
 * with canonical and legacy fallbacks.
 */

import type { RawAuditHistoryEntry } from "@/types/aiStrategist";

/* ------------------------------------------------------------------ */
/*  Score extraction                                                   */
/* ------------------------------------------------------------------ */

export type AuditListScores = {
  seo: number;
  geo: number;
  aeo: number;
};

/** Resolve a numeric score from a chain of optional sources, default 0. */
const num = (...values: unknown[]): number => {
  for (const v of values) {
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return 0;
};

/**
 * Extract SEO / GEO / Answer Engine Indexs from a RawAuditHistoryEntry.
 *
 * Priority order:
 *  1. Top-level `entry.seo_score` / `geo_score` / `aeo_score` (legacy rows)
 *  2. `entry.full_report.scores.seo` / `.geo` / `.aeo` (canonical payload)
 *  3. Falls back to 0.
 */
export const extractAuditListScores = (entry: RawAuditHistoryEntry): AuditListScores => {
  const report =
    typeof entry.full_report === "object" && entry.full_report !== null
      ? (entry.full_report as Record<string, unknown>)
      : undefined;

  const scores =
    typeof report?.scores === "object" && report.scores !== null
      ? (report.scores as Record<string, unknown>)
      : undefined;

  return {
    seo: num(entry.seo_score, scores?.seo),
    geo: num(entry.geo_score, scores?.geo),
    aeo: num(entry.aeo_score, scores?.aeo),
  };
};

/* ------------------------------------------------------------------ */
/*  URL extraction                                                     */
/* ------------------------------------------------------------------ */

/**
 * Safely extract display URL from a RawAuditHistoryEntry.
 *
 * Priority order:
 *  1. `entry.target_url`
 *  2. `entry.url`
 *  3. `entry.full_report.target.url`
 *  4. `entry.full_report.url`
 *  5. `entry.full_report.site.url`
 *  6. `entry.target_name`
 *  7. "Unknown URL"
 */
export const extractAuditUrl = (entry: RawAuditHistoryEntry): string => {
  if (entry.target_url) return entry.target_url;
  if (entry.url) return entry.url;

  const report =
    typeof entry.full_report === "object" && entry.full_report !== null
      ? (entry.full_report as Record<string, unknown>)
      : undefined;

  const target =
    typeof report?.target === "object" && report.target !== null
      ? (report.target as Record<string, unknown>)
      : undefined;

  if (typeof target?.url === "string" && target.url) return target.url as string;

  if (typeof report?.url === "string" && report.url) return report.url;

  const site =
    typeof report?.site === "object" && report.site !== null
      ? (report.site as Record<string, unknown>)
      : undefined;

  if (typeof site?.url === "string" && site.url) return site.url as string;

  if (entry.target_name) return entry.target_name;

  return "Unknown URL";
};

/* ------------------------------------------------------------------ */
/*  Date formatting                                                    */
/* ------------------------------------------------------------------ */

/**
 * Format an audit date string safely.
 * Returns "N/A" for null / undefined / invalid dates.
 * Falls back to canonical `metadata.created_at` if the top-level value is missing.
 */
export const formatAuditDate = (entry: RawAuditHistoryEntry): string => {
  const raw = entry.created_at ?? getCanonicalCreatedAt(entry);

  if (!raw) return "N/A";

  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "N/A";

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const getCanonicalCreatedAt = (entry: RawAuditHistoryEntry): string | null => {
  const report =
    typeof entry.full_report === "object" && entry.full_report !== null
      ? (entry.full_report as Record<string, unknown>)
      : undefined;

  const metadata =
    typeof report?.metadata === "object" && report.metadata !== null
      ? (report.metadata as Record<string, unknown>)
      : undefined;

  return typeof metadata?.created_at === "string" ? metadata.created_at : null;
};

/* ------------------------------------------------------------------ */
/*  Status resolution                                                  */
/* ------------------------------------------------------------------ */

export type AuditDisplayStatus =
  | "completed"
  | "failed"
  | "degraded"
  | "archived"
  | "purged"
  | "unknown";

export const extractAuditStatus = (entry: RawAuditHistoryEntry): AuditDisplayStatus => {
  const raw = entry.status?.toLowerCase?.() ?? "";
  if (raw === "completed" || raw === "succeeded" || raw === "ready") return "completed";
  if (raw === "failed") return "failed";
  if (raw === "degraded") return "degraded";
  if (raw === "archived") return "archived";
  if (raw === "purged") return "purged";
  return "unknown";
};

/* ------------------------------------------------------------------ */
/*  Score badge styling                                                */
/* ------------------------------------------------------------------ */

/**
 * Returns Tailwind classes for a score badge based on the value.
 *  ≥ 80 → green
 *  50-79 → amber
 *  < 50  → rose
 */
export const scoreBadgeClasses = (score: number): string => {
  if (score >= 80) return "text-emerald-300 bg-emerald-500/15";
  if (score >= 50) return "text-amber-300 bg-amber-500/15";
  return "text-rose-300 bg-rose-500/15";
};

/**
 * Returns Tailwind classes for a status badge.
 */
export const statusBadgeClasses = (status: AuditDisplayStatus): string => {
  switch (status) {
    case "completed":
      return "text-emerald-300 bg-emerald-500/15";
    case "failed":
      return "text-rose-300 bg-rose-500/15";
    case "degraded":
      return "text-amber-300 bg-amber-500/15";
    case "archived":
      return "text-sky-300 bg-sky-500/15";
    case "purged":
      return "text-zinc-400 bg-zinc-500/15";
    default:
      return "text-slate-300 bg-slate-500/15";
  }
};

/* ------------------------------------------------------------------ */
/*  Project Filtering                                                   */
/* ------------------------------------------------------------------ */

/**
 * Safely determines if an assessment history entry belongs to a specific project ID.
 * Checks top-level project fields first, then legacy site aliases and nested report objects.
 */
export const belongsToProject = (entry: unknown, projectId: number): boolean => {
  if (!entry || typeof entry !== "object") {
    return false;
  }

  const objectEntry = entry as Record<string, unknown>;
  const directProjectId = Number(objectEntry.project_id);
  if (Number.isInteger(directProjectId) && directProjectId === projectId) {
    return true;
  }

  const directSiteId = Number(objectEntry.site_id);
  if (Number.isInteger(directSiteId) && directSiteId === projectId) {
    return true;
  }

  const report =
    objectEntry.full_report && typeof objectEntry.full_report === "object"
      ? (objectEntry.full_report as Record<string, unknown>)
      : null;
  const reportProjectId = Number(report?.project_id);
  if (Number.isInteger(reportProjectId) && reportProjectId === projectId) {
    return true;
  }

  const reportSiteId = Number(report?.site_id);
  if (Number.isInteger(reportSiteId) && reportSiteId === projectId) {
    return true;
  }

  const site =
    report?.site && typeof report.site === "object"
      ? (report.site as Record<string, unknown>)
      : null;
  const nestedProjectId = Number(site?.project_id ?? site?.id ?? site?.site_id);

  return Number.isInteger(nestedProjectId) && nestedProjectId === projectId;
};

export const belongsToSite = belongsToProject;
