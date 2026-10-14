import type { ProjectAuditHistoryEntry } from "@/services/workspaceService";
import type { AuditTargetType, AuditResult } from "@/types/auditResult";
import type { AuditRecordResponse } from "@/types/auditWorkspace";

type AuditTargetShape = {
  target?: {
    type?: AuditTargetType;
    name?: string | null;
    url?: string | null;
  };
};

type AuditTargetRecord = Pick<
  ProjectAuditHistoryEntry,
  "audit_target_type" | "target_name" | "target_url" | "url"
>;

export type ProjectAuditTargetInfo = {
  type: AuditTargetType;
  label: string;
  url: string;
};

type ProjectAuditLaunchTarget = {
  targetType: AuditTargetType;
  targetName?: string | null;
  targetUrl?: string | null;
};

export function formatProjectAuditScore(value: number | null | undefined): string {
  return typeof value === "number" ? String(Math.round(value)) : "--";
}

export function buildAuditRecordResponse(audit: ProjectAuditHistoryEntry): AuditRecordResponse {
  return {
    id: audit.id,
    url: audit.url,
    audit_target_type: audit.audit_target_type,
    target_name: audit.target_name,
    target_url: audit.target_url,
    target_metadata: audit.target_metadata,
    geo_score: audit.geo_score,
    seo_score: typeof audit.seo_score === "number" ? audit.seo_score : undefined,
    aeo_score: typeof audit.aeo_score === "number" ? audit.aeo_score : undefined,
    status: audit.status,
    audit_type: audit.audit_type,
    created_at: audit.created_at,
    full_report: (audit.full_report as Record<string, unknown> | null) ?? undefined,
  };
}

export function resolveProjectAuditTarget(
  audit: AuditTargetRecord | null | undefined,
  report?: AuditTargetShape | AuditResult | null
): ProjectAuditTargetInfo {
  const type: AuditTargetType =
    report?.target?.type === "brand" || audit?.audit_target_type === "brand" ? "brand" : "website";

  const label = (
    report?.target?.name ??
    audit?.target_name ??
    report?.target?.url ??
    audit?.target_url ??
    audit?.url ??
    ""
  ).trim();

  const url = (report?.target?.url ?? audit?.target_url ?? audit?.url ?? "").trim();

  return {
    type,
    label,
    url,
  };
}

export function buildProjectAuditLaunchHref(
  projectId: string | number,
  launchTier: "fast" | "smart" | "deep",
  target: ProjectAuditLaunchTarget
): string {
  const query = new URLSearchParams({
    projectId: String(projectId),
    tab: "overview",
    targetType: target.targetType,
    tier: launchTier,
  });

  const targetUrl = target.targetUrl?.trim() ?? "";
  const targetName = target.targetName?.trim() ?? "";

  if (targetUrl) {
    query.set("url", targetUrl);
  }
  if (target.targetType === "brand" && targetName) {
    query.set("targetName", targetName);
  }

  return `/dashboard/audit?${query.toString()}`;
}
