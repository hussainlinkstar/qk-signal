import type {
  ExportVariantEntitlement,
  ExportVariantEntitlementsResponse,
  ExportVariantKey,
} from "@/services/reportService";

/**
 * `GET /api/v1/reports/export-variants` as the backend answers it (SIGV2-1124,
 * report kinds per SIGV2-1255).
 *
 * The shapes below are the real ones: `required_capability` and
 * `required_plan` are the keys `backend/services/report_export_variants.py`
 * reports, and `required_plan_label` is the plan name from the plan catalogue.
 * The default is a Starter plan: the four report kinds are all unlocked
 * (they ride on `has_pdf_audit_reports`, which every plan holds), and only
 * the Competitors report is locked.
 *
 * There is no override field. Every variant's `locked` state is the plan's
 * real answer for that variant's own capability, so a test that wants a
 * variant unlocked overrides `locked` and nothing else.
 */

const ROWS: Record<ExportVariantKey, ExportVariantEntitlement> = {
  standard: {
    key: "standard",
    report_type: "standard",
    report_kind: "standard",
    template_type: "Executive",
    locked: false,
    required_capability: "has_pdf_audit_reports",
    required_plan: "plan_starter",
    required_plan_label: "Starter",
  },
  executive: {
    key: "executive",
    report_type: "standard",
    report_kind: "executive",
    template_type: "Executive",
    locked: false,
    required_capability: "has_pdf_audit_reports",
    required_plan: "plan_starter",
    required_plan_label: "Starter",
  },
  aio: {
    key: "aio",
    report_type: "standard",
    report_kind: "aio",
    template_type: "Executive",
    locked: false,
    required_capability: "has_pdf_audit_reports",
    required_plan: "plan_starter",
    required_plan_label: "Starter",
  },
  seo: {
    key: "seo",
    report_type: "standard",
    report_kind: "seo",
    template_type: "Executive",
    locked: false,
    required_capability: "has_pdf_audit_reports",
    required_plan: "plan_starter",
    required_plan_label: "Starter",
  },
  competitors: {
    key: "competitors",
    report_type: "standard",
    report_kind: "competitors",
    template_type: "Executive",
    locked: true,
    required_capability: "has_competitor_analysis",
    required_plan: "plan_specialist",
    required_plan_label: "Specialist",
  },
};

export function exportVariantsResponse(
  overrides: Partial<Record<ExportVariantKey, Partial<ExportVariantEntitlement>>> = {},
  plan = "plan_starter"
): ExportVariantEntitlementsResponse {
  return {
    plan,
    variants: (Object.keys(ROWS) as ExportVariantKey[]).map((key) => ({
      ...ROWS[key],
      ...(overrides[key] ?? {}),
    })),
  };
}

/** Specialist: the first plan `CAPABILITY_MATRIX` grants `has_competitor_analysis`. */
export function specialistExportVariantsResponse(): ExportVariantEntitlementsResponse {
  return exportVariantsResponse({ competitors: { locked: false } }, "plan_specialist");
}
