import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_SECTIONS,
  generateAuditPdfReport,
  mapReportSectionsToBackendSections,
} from "@/lib/generateAuditPdfReport";

vi.mock("@/services/reportService", () => ({
  generateComplexReportPdf: vi.fn(),
  fetchComplexReportStatus: vi.fn(),
  downloadComplexReportPdfBlob: vi.fn(),
}));

import {
  downloadComplexReportPdfBlob,
  fetchComplexReportStatus,
  generateComplexReportPdf,
} from "@/services/reportService";
import { DEFAULT_BRANDING } from "@/lib/reportBranding";

const reportFixture = {
  schema_version: "2.0",
  url: "https://example.com",
  site: {
    url: "https://example.com",
    language: "fr",
  },
  target: {
    type: "website" as const,
    name: "Example",
    url: "https://example.com",
    metadata: {},
  },
  analysis: {},
  performance: {},
  network: {},
  warnings: [],
  metadata: {},
};

const metaFixture = {
  id: 42,
  url: "https://example.com",
  geoScore: 64,
  seoScore: 58,
  aeoScore: 47,
  status: "completed",
  auditType: "DEEP",
  createdAt: "2026-03-08T12:00:00.000Z",
};

describe("mapReportSectionsToBackendSections", () => {
  it("maps visible export options onto backend report sections", () => {
    expect(
      mapReportSectionsToBackendSections({
        seo: true,
        aeo: true,
        geo: true,
        technical: true,
        ai: true,
        competitors: false,
      })
    ).toEqual(["overview", "seo", "aeo", "geo", "cwv", "ai"]);
  });

  it("keeps optional sections opt-in and deduped", () => {
    expect(
      mapReportSectionsToBackendSections({
        ...DEFAULT_SECTIONS,
        technical: false,
        competitors: true,
      })
    ).toEqual(["overview", "seo", "aeo", "geo", "ai", "competitors"]);
  });
});

describe("generateAuditPdfReport", () => {
  const createObjectURL = vi.fn(() => "blob:report");
  const revokeObjectURL = vi.fn();
  let clickSpy: ReturnType<typeof vi.spyOn> | null = null;

  beforeEach(() => {
    vi.mocked(generateComplexReportPdf).mockReset();
    vi.mocked(fetchComplexReportStatus).mockReset();
    vi.mocked(downloadComplexReportPdfBlob).mockReset();
    createObjectURL.mockReset();
    revokeObjectURL.mockReset();
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    vi.stubGlobal("URL", {
      createObjectURL,
      revokeObjectURL,
    });
  });

  afterEach(() => {
    clickSpy?.mockRestore();
    clickSpy = null;
    vi.unstubAllGlobals();
  });

  it("queues an executive backend export and downloads the generated file", async () => {
    vi.mocked(generateComplexReportPdf).mockResolvedValue({
      report_id: "report-123",
      status: "queued",
      template_type: "Executive",
      generated_at: "2026-03-08T12:00:00.000Z",
      audit_count: 1,
      executive_summary: null,
      aggregate: null,
      download_url: null,
    });
    vi.mocked(fetchComplexReportStatus).mockResolvedValue({
      report_id: "report-123",
      status: "succeeded",
      download_url: "/api/v1/reports/complex/report-123/download",
    });
    vi.mocked(downloadComplexReportPdfBlob).mockResolvedValue({
      blob: new Blob(["pdf"], { type: "application/pdf" }),
      filename: "backend-file.pdf",
    });

    await generateAuditPdfReport(reportFixture, metaFixture);

    // No branding argument is passed, so DEFAULT_BRANDING applies. The colours
    // are asserted through it rather than as literals: they used to be hardcoded
    // to the old orange #FF4D2D and went stale when the palette moved to Atlas
    // Blue. This is not a white-label defect, callers pass branding explicitly.
    expect(generateComplexReportPdf).toHaveBeenCalledWith({
      audit_ids: [42],
      project_id: undefined,
      template_type: "Executive",
      report_options: {
        mode: "individual",
        sections: ["overview", "seo", "aeo", "geo", "cwv", "ai"],
        report_type: "standard",
        report_kind: "standard",
        branding_mode: "platform",
        hide_credit_cost: true,
        primary_color: DEFAULT_BRANDING.primaryColor,
        secondary_color: DEFAULT_BRANDING.secondaryColor,
        language: "fr",
      },
    });
    expect(fetchComplexReportStatus).toHaveBeenCalledWith("report-123");
    expect(downloadComplexReportPdfBlob).toHaveBeenCalledWith("report-123");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("surfaces failed backend exports", async () => {
    vi.mocked(generateComplexReportPdf).mockResolvedValue({
      report_id: "report-456",
      status: "queued",
      template_type: "Executive",
      generated_at: "2026-03-08T12:00:00.000Z",
      audit_count: 1,
      executive_summary: null,
      aggregate: null,
      download_url: null,
    });
    vi.mocked(fetchComplexReportStatus).mockResolvedValue({
      report_id: "report-456",
      status: "failed",
      error: "worker error",
    });

    await expect(generateAuditPdfReport(reportFixture, metaFixture)).rejects.toThrow(
      "worker error"
    );
    expect(downloadComplexReportPdfBlob).not.toHaveBeenCalled();
  });
});
