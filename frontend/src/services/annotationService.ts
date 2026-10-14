import { requestJson } from "@/services/http";

export type AnnotationVisibility = "internal" | "client_visible";

export type ReportAnnotation = {
  id: number;
  audit_id: number;
  project_id: number;
  user_id: number | null;
  user_display_name: string | null;
  parent_id: number | null;
  section_path: string | null;
  source_recommendation_key: string | null;
  content: string;
  visibility: AnnotationVisibility | string;
  is_deleted: boolean;
  created_at: string;
  updated_at: string | null;
  can_edit: boolean;
  can_delete: boolean;
  replies: ReportAnnotation[];
};

export type AnnotationThreadPage = {
  items: ReportAnnotation[];
  page: number;
  per_page: number;
  total: number;
  has_more: boolean;
};

export type AnnotationCreatePayload = {
  section_path?: string | null;
  source_recommendation_key?: string | null;
  content: string;
  visibility?: AnnotationVisibility;
  parent_id?: number | null;
};

export type AnnotationUpdatePayload = {
  content?: string | null;
  visibility?: AnnotationVisibility;
};

type AnnotationListOptions = {
  sectionPath?: string | null;
  sourceRecommendationKey?: string | null;
  visibility?: AnnotationVisibility;
  page?: number;
  perPage?: number;
};

const buildAnnotationQuery = (options: AnnotationListOptions = {}) => {
  const query = new URLSearchParams();
  if (options.sectionPath) {
    query.set("section_path", options.sectionPath);
  }
  if (options.sourceRecommendationKey) {
    query.set("source_recommendation_key", options.sourceRecommendationKey);
  }
  if (options.visibility) {
    query.set("visibility", options.visibility);
  }
  if (typeof options.page === "number") {
    query.set("page", String(options.page));
  }
  if (typeof options.perPage === "number") {
    query.set("per_page", String(options.perPage));
  }
  return query.toString();
};

export async function fetchAuditAnnotations(
  auditId: string | number,
  headers: HeadersInit = {},
  options: AnnotationListOptions = {}
): Promise<AnnotationThreadPage> {
  const query = buildAnnotationQuery(options);
  return requestJson<AnnotationThreadPage>({
    endpoint: query
      ? `/api/audits/${auditId}/annotations?${query}`
      : `/api/audits/${auditId}/annotations`,
    method: "GET",
    headers,
    errorMessage: "Unable to load report annotations.",
  });
}

export async function createAuditAnnotation(
  auditId: string | number,
  payload: AnnotationCreatePayload,
  headers: HeadersInit = {}
): Promise<ReportAnnotation> {
  return requestJson<ReportAnnotation>({
    endpoint: `/api/audits/${auditId}/annotations`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to save report annotation.",
  });
}

export async function updateAuditAnnotation(
  auditId: string | number,
  annotationId: string | number,
  payload: AnnotationUpdatePayload,
  headers: HeadersInit = {}
): Promise<ReportAnnotation> {
  return requestJson<ReportAnnotation>({
    endpoint: `/api/audits/${auditId}/annotations/${annotationId}`,
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to update report annotation.",
  });
}

export async function deleteAuditAnnotation(
  auditId: string | number,
  annotationId: string | number,
  headers: HeadersInit = {}
): Promise<ReportAnnotation> {
  return requestJson<ReportAnnotation>({
    endpoint: `/api/audits/${auditId}/annotations/${annotationId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to delete report annotation.",
  });
}

export async function fetchPortalAuditAnnotations(
  projectId: string | number,
  auditId: string | number,
  headers: HeadersInit = {},
  options: AnnotationListOptions = {}
): Promise<AnnotationThreadPage> {
  const query = buildAnnotationQuery(options);
  const endpoint = query
    ? `/api/portal/projects/${projectId}/audits/${auditId}/annotations?${query}`
    : `/api/portal/projects/${projectId}/audits/${auditId}/annotations`;
  return requestJson<AnnotationThreadPage>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load portal annotations.",
  });
}

export async function createPortalAnnotationReply(
  projectId: string | number,
  auditId: string | number,
  payload: AnnotationCreatePayload,
  headers: HeadersInit = {}
): Promise<ReportAnnotation> {
  return requestJson<ReportAnnotation>({
    endpoint: `/api/portal/projects/${projectId}/audits/${auditId}/annotations`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to send annotation reply.",
  });
}
