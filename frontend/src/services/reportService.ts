import { parseErrorDetail, requestJson, withJsonContentType } from "@/services/http";

export type ReportTemplateType = "Technical" | "Executive" | "Comparative";
export type ReportType = "standard" | "battle" | "branded" | "whitelabel";
export type WhiteLabelReportType = Extract<ReportType, "standard" | "branded" | "whitelabel">;
export type ReportKind =
  | "standard"
  | "executive"
  | "project"
  | "competitors"
  | "financial"
  | "aio"
  | "seo";
export type BrandingMode = "platform" | "white_label";
export type CompetitorMode = "latest" | "trend";

export type ComplexReportGenerateRequest = {
  audit_ids: number[];
  template_type: ReportTemplateType;
  project_id?: number;
  site_id?: number;
  date_from?: string | null;
  date_to?: string | null;
  report_options?: {
    mode?: "individual" | "aggregated";
    sections?: Array<"overview" | "geo" | "seo" | "aeo" | "cwv" | "ai" | "competitors">;
    report_type?: ReportType;
    report_kind?: ReportKind;
    branding_mode?: BrandingMode;
    competitor_mode?: CompetitorMode;
    hide_credit_cost?: boolean;
    footer_text?: string | null;
    competitors?: number[];
    comparison_competitor_name?: string | null;
    comparison_competitor_rank?: number | null;
    primary_color?: string | null;
    secondary_color?: string | null;
    language?: string | null;
  };
};

type BackendComplexReportGenerateRequest = Omit<ComplexReportGenerateRequest, "project_id"> & {
  site_id?: number;
};

function normalizeComparisonCompetitorRank(rank: number | null | undefined): number | undefined {
  return typeof rank === "number" && Number.isInteger(rank) && rank > 0 ? rank : undefined;
}

export type ComplexReportGenerateResponse = {
  report_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  template_type: string;
  generated_at: string;
  audit_count: number;
  executive_summary: string | null;
  aggregate: Record<string, unknown> | null;
  download_url: string | null;
};

export type ComplexReportStatusResponse = {
  report_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "expired";
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  download_url?: string | null;
  expired?: boolean;
  retention_days?: number;
};

export type ComplexReportPdfDownloadResponse = {
  blob: Blob;
  filename: string | null;
};

export type ReportLibraryStatus = "queued" | "running" | "succeeded" | "failed" | "expired";

/**
 * One row of the Report library. Every value is served by the backend, never
 * assembled in the browser: in particular `link_expired` and
 * `link_expiry_days_remaining` are the backend's answer about the stored
 * artifact, so the Link expiry column reports a dead link instead of the
 * customer discovering it by clicking.
 */
export type ReportLibraryItem = {
  report_id: string;
  name: string;
  report_kind: string | null;
  period_start: string | null;
  period_end: string | null;
  created_at: string | null;
  size_bytes: number | null;
  status: ReportLibraryStatus;
  error: string | null;
  expires_at: string | null;
  link_expired: boolean;
  link_expiry_days_remaining: number | null;
  retention_days: number;
  download_url: string | null;
};

export type ReportLibraryResponse = {
  items: ReportLibraryItem[];
  total: number;
  limit: number;
  offset: number;
};

export type ReportLibraryDeleteResponse = {
  deleted: string[];
  not_found: string[];
};

export async function fetchReportLibrary(
  headers: HeadersInit = {},
  options: { limit?: number; offset?: number } = {}
): Promise<ReportLibraryResponse> {
  const params = new URLSearchParams();
  if (typeof options.limit === "number") params.set("limit", String(options.limit));
  if (typeof options.offset === "number") params.set("offset", String(options.offset));
  const query = params.toString();
  return requestJson<ReportLibraryResponse>({
    endpoint: `/api/v1/reports/complex${query ? `?${query}` : ""}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load your reports.",
  });
}

export async function deleteReports(
  reportIds: string[],
  headers: HeadersInit = {}
): Promise<ReportLibraryDeleteResponse> {
  return requestJson<ReportLibraryDeleteResponse>({
    endpoint: "/api/v1/reports/complex/delete",
    method: "POST",
    headers,
    body: { report_ids: reportIds },
    errorMessage: "Unable to delete the selected reports.",
  });
}

export type ExportVariantKey = "standard" | "executive" | "aio" | "seo" | "competitors";

/**
 * One row of the Export report menu, as the backend resolved it for the
 * signed-in user's plan (SIGV2-1124, report kinds per SIGV2-1255).
 *
 * `locked` is the only thing the menu gates on. It is computed by the same
 * policy objects `POST /api/v1/reports/generate-complex` enforces, so the menu
 * cannot advertise something the enqueue endpoint would refuse, and cannot
 * lock something the plan actually includes. Never recompute it here from a
 * client-side plan table, and never add a second field that can override it.
 */
export type ExportVariantEntitlement = {
  key: ExportVariantKey;
  report_type: ReportType;
  report_kind: ReportKind | null;
  template_type: ReportTemplateType;
  locked: boolean;
  required_capability: string | null;
  required_plan: string | null;
  required_plan_label: string | null;
};

export type ExportVariantEntitlementsResponse = {
  plan: string | null;
  variants: ExportVariantEntitlement[];
};

export type WhiteLabelBrandingResponse = {
  custom_logo_url: string | null;
  company_name: string | null;
  primary_color: string | null;
  secondary_color: string | null;
};

export type WhiteLabelReportRequest = {
  audit_id: number;
  agency_name?: string | null;
  title?: string | null;
  logo_data_url?: string | null;
  report_date?: string | null;
  report_type?: WhiteLabelReportType;
  report_kind?: ReportKind;
  branding_mode?: BrandingMode;
  competitor_mode?: CompetitorMode;
  hide_credit_cost?: boolean;
  footer_text?: string | null;
  primary_color?: string | null;
  secondary_color?: string | null;
  language?: string | null;
  include_competitor_analysis?: boolean;
};

export type WhiteLabelReportQueuedResponse = {
  report_id: string;
  status: "queued";
  poll_url: string;
};

export async function fetchWhiteLabelBranding(
  headers: HeadersInit = {}
): Promise<WhiteLabelBrandingResponse> {
  return requestJson<WhiteLabelBrandingResponse>({
    endpoint: "/api/v1/users/me/branding",
    method: "GET",
    headers,
    errorMessage: "Unable to load white-label branding settings.",
  });
}

export async function generateComplexReportPdf(
  payload: ComplexReportGenerateRequest,
  headers: HeadersInit = {}
): Promise<ComplexReportGenerateResponse> {
  const { project_id, site_id, report_options, ...rest } = payload;
  const normalizedReportOptions = report_options
    ? {
        ...report_options,
        comparison_competitor_rank: normalizeComparisonCompetitorRank(
          report_options.comparison_competitor_rank
        ),
      }
    : undefined;
  const normalizedPayload: BackendComplexReportGenerateRequest = {
    ...rest,
    ...(normalizedReportOptions ? { report_options: normalizedReportOptions } : {}),
    ...(typeof site_id === "number"
      ? { site_id }
      : typeof project_id === "number"
        ? { site_id: project_id }
        : {}),
  };

  return requestJson<ComplexReportGenerateResponse>({
    endpoint: "/api/v1/reports/generate-complex",
    method: "POST",
    headers,
    body: normalizedPayload,
    errorMessage: "Unable to generate report PDF.",
  });
}

export async function generateWhiteLabelReportPdf(
  payload: WhiteLabelReportRequest,
  headers: HeadersInit = {}
): Promise<WhiteLabelReportQueuedResponse> {
  return requestJson<WhiteLabelReportQueuedResponse>({
    endpoint: "/api/v1/reports/white-label/pdf",
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to generate white-label report PDF.",
  });
}

export async function fetchReportExportVariants(
  headers: HeadersInit = {}
): Promise<ExportVariantEntitlementsResponse> {
  return requestJson<ExportVariantEntitlementsResponse>({
    endpoint: "/api/v1/reports/export-variants",
    method: "GET",
    headers,
    errorMessage: "Unable to load report export options.",
  });
}

export async function fetchComplexReportStatus(
  reportId: string,
  headers: HeadersInit = {}
): Promise<ComplexReportStatusResponse> {
  return requestJson<ComplexReportStatusResponse>({
    endpoint: `/api/v1/reports/complex/${reportId}/status`,
    method: "GET",
    headers,
    errorMessage: "Unable to load report job status.",
  });
}

export async function downloadComplexReportPdfBlob(
  reportId: string,
  headers: HeadersInit = {}
): Promise<ComplexReportPdfDownloadResponse> {
  const response = await fetch(`/api/v1/reports/complex/${reportId}/download`, {
    method: "GET",
    headers: withJsonContentType(headers),
  });

  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, "Unable to download report PDF."));
  }

  const blob = await response.blob();
  const contentDisposition = response.headers.get("content-disposition");
  const filename = resolveFilenameFromContentDisposition(contentDisposition);
  return { blob, filename };
}

function resolveFilenameFromContentDisposition(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      return utf8Match[1].trim();
    }
  }

  const quotedMatch = value.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1].trim();
  }

  const bareMatch = value.match(/filename=([^;]+)/i);
  if (bareMatch?.[1]) {
    return bareMatch[1].trim();
  }

  return null;
}
