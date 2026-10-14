import { requestJson } from "@/services/http";

export type PortalBranding = {
  workspace_id: number;
  workspace_name: string;
  agency_name: string | null;
  custom_logo_url: string | null;
  primary_color: string | null;
  secondary_color: string | null;
  custom_favicon_url?: string | null;
  custom_page_title?: string | null;
  hide_powered_by?: boolean;
};

export type PortalProjectSummary = {
  id: number;
  workspace_id: number;
  name: string;
  domain_url: string | null;
  language: string;
  latest_seo_score: number | null;
  latest_geo_score: number | null;
  latest_aeo_score: number | null;
  last_audit_at: string | null;
};

export type PortalApprovalInfo = {
  status: string;
  decided_at: string | null;
  note: string | null;
};

export type PortalRecommendation = {
  title: string;
  description: string | null;
  section_path: string | null;
  source_recommendation_key: string | null;
  annotation_count: number;
  approval: PortalApprovalInfo | null;
};

export type PortalLatestAudit = {
  id: number;
  created_at: string | null;
  status: string;
  seo_score: number | null;
  geo_score: number | null;
  aeo_score: number | null;
  summary: string | null;
};

export type PortalTrendPoint = {
  created_at: string | null;
  seo_score: number | null;
  geo_score: number | null;
  aeo_score: number | null;
};

export type PortalLatestReport = {
  report_month: string | null;
  created_at: string | null;
  expired: boolean;
  retention_days: number;
};

export type PortalProjectDashboard = {
  project: PortalProjectSummary;
  latest_audit: PortalLatestAudit | null;
  latest_report: PortalLatestReport | null;
  trends: PortalTrendPoint[];
  recommendations: PortalRecommendation[];
};

export type PortalTask = {
  id: number;
  issue_key: string;
  issue_url: string;
  title: string;
  issue_type: string;
  status_name: string;
  created_at: string | null;
};

export type PortalAuditHistoryItem = {
  id: number;
  created_at: string | null;
  seo_score: number | null;
  geo_score: number | null;
  aeo_score: number | null;
  status: string;
};

export type PortalAuditHistoryResponse = {
  items: PortalAuditHistoryItem[];
  total: number;
  page: number;
  page_size: number;
};

export type PortalRecommendationApproval = {
  id: number;
  audit_id: number;
  source_recommendation_key: string;
  section_path: string | null;
  status: string;
  decided_at: string | null;
  note: string | null;
};

export type PortalPreferences = {
  email_digest_frequency: string | null;
  notify_on_new_audit: boolean | null;
};

export async function fetchPortalBranding(headers: HeadersInit = {}): Promise<PortalBranding> {
  return requestJson<PortalBranding>({
    endpoint: "/api/portal/branding",
    method: "GET",
    headers,
    errorMessage: "Unable to load portal branding.",
  });
}

export async function fetchPortalProjects(
  headers: HeadersInit = {}
): Promise<PortalProjectSummary[]> {
  return requestJson<PortalProjectSummary[]>({
    endpoint: "/api/portal/projects",
    method: "GET",
    headers,
    errorMessage: "Unable to load assigned portal projects.",
  });
}

export async function fetchPortalProjectDashboard(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<PortalProjectDashboard> {
  return requestJson<PortalProjectDashboard>({
    endpoint: `/api/portal/projects/${projectId}/dashboard`,
    method: "GET",
    headers,
    errorMessage: "Unable to load portal dashboard.",
  });
}

export async function fetchPortalProjectTasks(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<PortalTask[]> {
  return requestJson<PortalTask[]>({
    endpoint: `/api/portal/projects/${projectId}/tasks`,
    method: "GET",
    headers,
    errorMessage: "Unable to load portal tasks.",
  });
}

export async function fetchPortalAuditHistory(
  projectId: string | number,
  page = 1,
  pageSize = 20,
  headers: HeadersInit = {}
): Promise<PortalAuditHistoryResponse> {
  return requestJson<PortalAuditHistoryResponse>({
    endpoint: `/api/portal/projects/${projectId}/audits?page=${page}&page_size=${pageSize}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load audit history.",
  });
}

export async function downloadPortalPdf(
  projectId: string | number,
  auditId: number
): Promise<void> {
  const res = await fetch(`/api/portal/projects/${projectId}/audits/${auditId}/pdf`, {
    credentials: "include",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "PDF download failed.");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `audit-${auditId}-report.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function submitRecommendationApproval(
  projectId: string | number,
  auditId: number,
  recommendationKey: string,
  status: "approved" | "rejected" | "deferred",
  note?: string
): Promise<PortalRecommendationApproval> {
  return requestJson<PortalRecommendationApproval>({
    endpoint: `/api/portal/projects/${projectId}/audits/${auditId}/recommendations/${encodeURIComponent(recommendationKey)}/approval`,
    method: "POST",
    body: { status, note: note || null },
    errorMessage: "Unable to submit recommendation approval.",
  });
}

export async function fetchPortalPreferences(
  headers: HeadersInit = {}
): Promise<PortalPreferences> {
  return requestJson<PortalPreferences>({
    endpoint: "/api/portal/profile/preferences",
    method: "GET",
    headers,
    errorMessage: "Unable to load preferences.",
  });
}

export async function updatePortalPreferences(
  prefs: Partial<PortalPreferences>
): Promise<PortalPreferences> {
  return requestJson<PortalPreferences>({
    endpoint: "/api/portal/profile/preferences",
    method: "PATCH",
    body: prefs,
    errorMessage: "Unable to update preferences.",
  });
}
