import type { CanonicalAuditReport } from "@/lib/reportAdapters";
import { normalizeReportLanguage } from "@/lib/reportLanguages";
import { DEFAULT_BRANDING, type ReportBranding } from "@/lib/reportBranding";
import {
  downloadComplexReportPdfBlob,
  fetchComplexReportStatus,
  generateComplexReportPdf,
  type ComplexReportGenerateRequest,
} from "@/services/reportService";
import type { AuditHistoryItem } from "@/types/auditWorkspace";

export type ReportSections = {
  seo: boolean;
  aeo: boolean;
  geo: boolean;
  technical: boolean;
  ai: boolean;
  competitors: boolean;
};

export const DEFAULT_SECTIONS: ReportSections = {
  seo: true,
  aeo: true,
  geo: true,
  technical: true,
  ai: true,
  competitors: false,
};

const REPORT_POLL_DELAY_MS = 2000;
const REPORT_MAX_POLL_ATTEMPTS = 45;

type BackendSection = ComplexReportGenerateRequest["report_options"] extends { sections?: infer T }
  ? T extends Array<infer U>
    ? U
    : never
  : never;

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const sanitizeFileSegment = (value: string): string => {
  const sanitized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return sanitized || "report";
};

const resolveAuditLabel = (report: CanonicalAuditReport, meta: AuditHistoryItem): string => {
  const candidates = [
    report.target?.name,
    report.target?.url,
    meta.targetName,
    meta.targetUrl,
    meta.url,
    report.url,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "audit-report";
};

const buildFallbackFilename = (report: CanonicalAuditReport, meta: AuditHistoryItem): string => {
  const segment = sanitizeFileSegment(resolveAuditLabel(report, meta));
  const date = new Date(meta.createdAt || Date.now()).toISOString().slice(0, 10);
  return `${segment}-audit-report-${date}.pdf`;
};

const triggerPdfDownload = (blob: Blob, filename: string): void => {
  const objectUrl = window.URL.createObjectURL(blob);
  const revokeObjectUrl =
    typeof window.URL?.revokeObjectURL === "function"
      ? window.URL.revokeObjectURL.bind(window.URL)
      : null;
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  if (revokeObjectUrl) {
    window.setTimeout(() => {
      revokeObjectUrl(objectUrl);
    }, 0);
  }
};

export const mapReportSectionsToBackendSections = (sections: ReportSections): BackendSection[] => {
  const mapped: BackendSection[] = ["overview"];

  if (sections.seo) {
    mapped.push("seo");
  }
  if (sections.aeo) {
    mapped.push("aeo");
  }
  if (sections.geo) {
    mapped.push("geo");
  }
  if (sections.technical) {
    mapped.push("cwv");
  }
  if (sections.ai) {
    mapped.push("ai");
  }
  if (sections.competitors) {
    mapped.push("competitors");
  }

  return mapped.filter((section, index) => mapped.indexOf(section) === index);
};

const waitForReportDownload = async (reportId: string, filename: string): Promise<void> => {
  for (let attempt = 0; attempt < REPORT_MAX_POLL_ATTEMPTS; attempt += 1) {
    if (attempt > 0) {
      await sleep(REPORT_POLL_DELAY_MS);
    }

    const status = await fetchComplexReportStatus(reportId);
    if (status.status === "succeeded") {
      const downloadPayload = await downloadComplexReportPdfBlob(reportId);
      triggerPdfDownload(downloadPayload.blob, downloadPayload.filename?.trim() || filename);
      return;
    }
    if (status.status === "failed") {
      throw new Error(status.error || "Report generation failed.");
    }
    if (status.status === "expired") {
      throw new Error(`Report expired and was removed after ${status.retention_days ?? 30} days.`);
    }
  }

  throw new Error("Report generation timed out. Please try again.");
};

const resolveReportLanguage = (report: CanonicalAuditReport): string =>
  normalizeReportLanguage(
    (typeof report.site?.language === "string" && report.site.language) ||
      (typeof report.metadata?.language === "string" && report.metadata.language) ||
      (typeof report.target?.metadata?.language === "string" && report.target.metadata.language) ||
      "en"
  );

export async function generateAuditPdfReport(
  report: CanonicalAuditReport,
  meta: AuditHistoryItem,
  sections: ReportSections = DEFAULT_SECTIONS,
  branding: ReportBranding = DEFAULT_BRANDING
): Promise<void> {
  if (!meta?.id) {
    throw new Error("Missing audit id for PDF export.");
  }

  const reportLanguage = resolveReportLanguage(report);
  const fallbackFilename = buildFallbackFilename(report, meta);
  const queuedReport = await generateComplexReportPdf({
    audit_ids: [meta.id],
    project_id: meta.projectId,
    template_type: "Executive",
    report_options: {
      mode: "individual",
      sections: mapReportSectionsToBackendSections(sections),
      report_type: "standard",
      report_kind: "standard",
      branding_mode: "platform",
      hide_credit_cost: true,
      primary_color: branding.primaryColor,
      secondary_color: branding.secondaryColor,
      language: reportLanguage,
    },
  });

  await waitForReportDownload(queuedReport.report_id, fallbackFilename);
}
