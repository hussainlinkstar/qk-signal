import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReportsPageClient from "@/app/(app)/dashboard/reports/generate/ReportsPageClient";
import {
  fetchProjectAudits,
  fetchProjectCompetitors,
  fetchWorkspaceProjects,
} from "@/services/workspaceService";
import {
  downloadComplexReportPdfBlob,
  fetchComplexReportStatus,
  fetchWhiteLabelBranding,
  generateComplexReportPdf,
  generateWhiteLabelReportPdf,
} from "@/services/reportService";

const authState = {
  getToken: vi.fn(async () => "token-123"),
  isSignedIn: true,
  isLoading: false,
  user: {
    id: "user-1",
    email: "owner@example.com",
    role: "user",
    permissions: [],
    subscription_plan: "plan_executive",
  },
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/services/workspaceService", () => ({
  fetchWorkspaceProjects: vi.fn(),
  fetchProjectAudits: vi.fn(),
  fetchProjectCompetitors: vi.fn(),
}));

vi.mock("@/services/reportService", () => ({
  downloadComplexReportPdfBlob: vi.fn(),
  fetchComplexReportStatus: vi.fn(),
  fetchWhiteLabelBranding: vi.fn(),
  generateComplexReportPdf: vi.fn(),
  generateWhiteLabelReportPdf: vi.fn(),
}));

async function openReportTypeStep() {
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^continue$/i })).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));

  await waitFor(() => {
    expect(screen.getByText(/choose the audit/i)).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /report type/i })).toBeInTheDocument();
  });
}

async function openConfigureStep(reportTypeLabel: RegExp) {
  await openReportTypeStep();

  const reportCard = screen
    .getAllByRole("button")
    .find(
      (button) =>
        button.getAttribute("aria-pressed") !== null &&
        reportTypeLabel.test(button.textContent ?? "")
    );

  if (!reportCard) {
    throw new Error(`Unable to find report card matching ${String(reportTypeLabel)}`);
  }

  fireEvent.click(reportCard);
  fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));

  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^back$/i })).toBeInTheDocument();
  });
}

describe("ReportsPageClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.getToken.mockResolvedValue("token-123");
    window.localStorage.clear();
    authState.user = {
      id: "user-1",
      email: "owner@example.com",
      role: "user",
      permissions: [],
      subscription_plan: "plan_executive",
    };

    const featureAccess = {
      monitoring: { allowed: true, detail: null, status_code: null, required_plan: null },
      automations: { allowed: true, detail: null, status_code: null, required_plan: null },
      entity_authority: { allowed: true, detail: null, status_code: null, required_plan: null },
      benchmark_intelligence: {
        allowed: true,
        detail: null,
        status_code: null,
        required_plan: null,
      },
      scheduled_audits: { allowed: true, detail: null, status_code: null, required_plan: null },
      jira_export: { allowed: true, detail: null, status_code: null, required_plan: null },
    };

    vi.mocked(fetchWorkspaceProjects).mockResolvedValue([
      {
        id: 21,
        workspace_id: 1,
        name: "Northwind",
        domain_url: "https://northwind.example",
        target_country: "RO",
        language: "ro",
        icp_roles: [],
        pain_points: null,
        usp: null,
        competitors: [],
        priority_pulse_tags: [],
        sme_profiles: [],
        created_at: null,
        audit_count: 3,
        last_audit_at: "2026-03-02T10:00:00.000Z",
        latest_seo_score: 74,
        latest_geo_score: 71,
        latest_aeo_score: 72,
        feature_access: featureAccess,
      },
    ]);
    vi.mocked(fetchProjectAudits).mockResolvedValue([
      {
        id: 301,
        project_id: 21,
        site_id: 41,
        audit_type: "STANDARD",
        url: "https://northwind.example",
        geo_score: 71,
        seo_score: 74,
        aeo_score: 72,
        status: "completed",
        created_at: "2026-03-02T10:00:00.000Z",
        full_report: {
          competitors: [
            {
              name: "Competitor A",
              score: 64,
              geo_visibility: 69,
              aeo_score: 61,
              entity_strength: 58,
              rank: 1,
            },
          ],
          hallucination: {
            flagged_claims: 0,
            total_claims: 6,
            flagged: false,
          },
        },
      },
    ]);
    vi.mocked(fetchProjectCompetitors).mockResolvedValue([
      {
        id: 17,
        project_id: 21,
        competitor_site_id: 51,
        target_url: "https://contoso.example",
        normalized_domain: "contoso.example",
        display_name: "Contoso",
        auto_audit_enabled: true,
        created_at: "2026-02-01T08:00:00.000Z",
        latest_status: "succeeded",
        latest_failure_reason: null,
        last_benchmarked_at: "2026-03-02T11:00:00.000Z",
        latest_source_audit_id: 901,
        latest_scores: {
          geo: 69,
          seo: 73,
          aeo: 71,
          overall: 71,
        },
      },
    ]);
    vi.mocked(fetchWhiteLabelBranding).mockResolvedValue({
      company_name: "Agency North",
      custom_logo_url: "https://assets.example/logo.png",
      primary_color: "#FF4D2D",
      secondary_color: "#E2E8F0",
    });
    vi.mocked(generateComplexReportPdf).mockResolvedValue({
      report_id: "report-123",
      status: "queued",
      template_type: "Executive",
      generated_at: "2026-03-03T10:00:00.000Z",
      audit_count: 1,
      executive_summary: null,
      aggregate: null,
      download_url: null,
    });
    vi.mocked(generateWhiteLabelReportPdf).mockResolvedValue({
      report_id: "report-456",
      status: "queued",
      poll_url: "/api/v1/reports/complex/report-456/status",
    });
    vi.mocked(fetchComplexReportStatus).mockResolvedValue({
      report_id: "report-123",
      status: "succeeded",
      download_url: "/api/v1/reports/complex/report-123/download",
    });
    vi.mocked(downloadComplexReportPdfBlob).mockResolvedValue({
      blob: new Blob(["pdf"]),
      filename: "Northwind_STANDARD_Executive_20260308T140000Z.pdf",
    });

    global.URL.createObjectURL = vi.fn(() => "blob:report");
    global.URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  it("includes the active workspace in report context requests", async () => {
    window.localStorage.setItem("active_workspace_id", "42");
    render(<ReportsPageClient />);

    await waitFor(() => {
      expect(fetchWorkspaceProjects).toHaveBeenCalledWith({
        Authorization: "Bearer token-123",
        "X-Workspace-Id": "42",
      });
    });
  });

  it("falls back to English for a stored Romanian project language and sends the chosen language to backend jobs", async () => {
    render(<ReportsPageClient />);

    await waitFor(() => {
      expect(screen.getByLabelText(/language/i)).toBeInTheDocument();
    });

    // Wait for the fetched project to resolve; the selectedProject effect
    // resets reportLanguage, so it must land before the language change.
    await screen.findByText("https://northwind.example");

    const languageSelect = screen.getByLabelText(/language/i) as HTMLSelectElement;
    await waitFor(() => {
      expect(languageSelect.value).toBe("en");
    });

    fireEvent.change(languageSelect, { target: { value: "ja" } });

    expect(screen.getByText("CJK font stack active")).toBeInTheDocument();

    await openConfigureStep(/standard pdf/i);

    fireEvent.click(screen.getByRole("button", { name: /generate standard pdf/i }));

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalledWith(
        {
          audit_ids: [301],
          project_id: 21,
          template_type: "Executive",
          report_options: {
            mode: "individual",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "standard",
            report_kind: "standard",
            branding_mode: "platform",
            hide_credit_cost: true,
            language: "ja",
          },
        },
        { Authorization: "Bearer token-123" }
      );
    });

    await waitFor(() => {
      expect(fetchComplexReportStatus).toHaveBeenCalledWith("report-123", {
        Authorization: "Bearer token-123",
      });
    });

    expect(downloadComplexReportPdfBlob).toHaveBeenCalledWith("report-123", {
      Authorization: "Bearer token-123",
    });
  });

  it("queues aggregated project exports with a custom date range", async () => {
    render(<ReportsPageClient />);

    await openConfigureStep(/project progress pdf/i);

    fireEvent.change(screen.getByLabelText(/coverage/i), {
      target: { value: "custom" },
    });
    fireEvent.change(screen.getByLabelText(/start date/i), {
      target: { value: "2026-02-01" },
    });
    fireEvent.change(screen.getByLabelText(/end date/i), {
      target: { value: "2026-03-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: /generate project pdf/i }));

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalledWith(
        {
          audit_ids: [301],
          site_id: 41,
          date_from: "2026-02-01T00:00:00.000Z",
          date_to: "2026-03-01T23:59:59.999Z",
          template_type: "Executive",
          report_options: {
            mode: "aggregated",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "standard",
            report_kind: "project",
            branding_mode: "platform",
            hide_credit_cost: true,
            language: "en",
          },
        },
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("queues all-time competitor trend exports from tracked project competitors", async () => {
    render(<ReportsPageClient />);

    await openConfigureStep(/competitors pdf/i);

    fireEvent.change(screen.getByLabelText(/mode/i), {
      target: { value: "trend" },
    });
    fireEvent.click(screen.getByRole("button", { name: /generate trend report/i }));

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalledWith(
        {
          audit_ids: [301],
          site_id: 41,
          template_type: "Comparative",
          report_options: {
            mode: "aggregated",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "battle",
            report_kind: "competitors",
            branding_mode: "platform",
            competitor_mode: "trend",
            competitors: [51],
            comparison_competitor_name: "Contoso",
            hide_credit_cost: true,
            language: "en",
          },
        },
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("shows battle export when canonical competitor data exists and sends the selected competitor to backend jobs", async () => {
    render(<ReportsPageClient />);

    await openConfigureStep(/competitors pdf/i);

    fireEvent.click(screen.getByRole("button", { name: /generate competitors pdf/i }));

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalledWith(
        {
          audit_ids: [301],
          project_id: 21,
          template_type: "Comparative",
          report_options: {
            mode: "individual",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "battle",
            report_kind: "competitors",
            branding_mode: "platform",
            competitor_mode: "latest",
            hide_credit_cost: true,
            language: "en",
            comparison_competitor_name: "Competitor A",
            comparison_competitor_rank: 1,
          },
        },
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("queues platform executive exports through the white-label endpoint", async () => {
    render(<ReportsPageClient />);

    await openConfigureStep(/executive pdf/i);

    fireEvent.click(screen.getByRole("button", { name: /generate platform executive pdf/i }));

    await waitFor(() => {
      expect(generateWhiteLabelReportPdf).toHaveBeenCalledWith(
        {
          audit_id: 301,
          agency_name: undefined,
          title: "AI Visibility Diagnostic Blueprint",
          report_type: "standard",
          report_kind: "executive",
          branding_mode: "platform",
          hide_credit_cost: true,
          footer_text: undefined,
          primary_color: undefined,
          secondary_color: undefined,
          language: "en",
          include_competitor_analysis: false,
        },
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("queues agency executive exports through the white-label endpoint with agency branding metadata", async () => {
    render(<ReportsPageClient />);

    await openConfigureStep(/executive pdf/i);

    fireEvent.click(screen.getByRole("button", { name: /generate agency executive pdf/i }));

    await waitFor(() => {
      expect(generateWhiteLabelReportPdf).toHaveBeenCalledWith(
        {
          audit_id: 301,
          agency_name: "Agency North",
          title: "Agency North AI Visibility Diagnostic Blueprint",
          report_type: "branded",
          report_kind: "executive",
          branding_mode: "platform",
          hide_credit_cost: true,
          footer_text: undefined,
          primary_color: "#FF4D2D",
          secondary_color: "#E2E8F0",
          language: "en",
          include_competitor_analysis: false,
        },
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("queues financial exports with the selected project-backed audit", async () => {
    render(<ReportsPageClient />);

    await openConfigureStep(/financial pdf/i);

    fireEvent.click(screen.getByRole("button", { name: /generate financial pdf/i }));

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalledWith(
        {
          audit_ids: [301],
          project_id: 21,
          template_type: "Executive",
          report_options: {
            mode: "individual",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "standard",
            report_kind: "financial",
            branding_mode: "platform",
            hide_credit_cost: true,
            language: "en",
          },
        },
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("locks premium executive variants and competitor reports when the current plan does not include them", async () => {
    authState.user = {
      id: "user-2",
      email: "starter@example.com",
      role: "user",
      permissions: [],
      subscription_plan: "plan_standard",
    };

    render(<ReportsPageClient />);

    await openConfigureStep(/executive pdf/i);

    expect(screen.getByRole("button", { name: /generate agency executive pdf/i })).toBeDisabled();
    // The white-label variant is off for the MVP, so it is absent rather than
    // rendered as a lock: a disabled upsell would point at a feature no plan
    // currently grants.
    expect(
      screen.queryByRole("button", { name: /generate white-label executive pdf/i })
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));

    const competitorsCard = screen
      .getAllByRole("button")
      .find(
        (button) =>
          button.getAttribute("aria-pressed") !== null &&
          /competitors pdf/i.test(button.textContent ?? "")
      );

    if (!competitorsCard) {
      throw new Error("Unable to find the competitors report card");
    }

    fireEvent.click(competitorsCard);
    fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /generate competitors report/i })
      ).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /generate competitors report/i })).toBeDisabled();
  });

  it("offers Standard, AIO, SEO, and Executive report types", async () => {
    render(<ReportsPageClient />);

    await openReportTypeStep();

    const buttons = screen
      .getAllByRole("button")
      .filter((button) => button.getAttribute("aria-pressed") !== null);
    const labels = buttons.map((button) => (button.textContent ?? "").toLowerCase());

    for (const kind of ["standard", "aio", "seo", "executive"]) {
      expect(labels.some((label) => new RegExp(`\\b${kind}\\b`).test(label))).toBe(true);
    }
  });

  it.each([
    ["AIO", "aio"],
    ["SEO", "seo"],
  ])("queues a %s report with report_kind %s", async (label, kind) => {
    render(<ReportsPageClient />);

    await openConfigureStep(new RegExp(`\\b${label}\\b`, "i"));
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`generate ${label}`, "i") }));

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalledWith(
        expect.objectContaining({
          audit_ids: [301],
          project_id: 21,
          report_options: expect.objectContaining({ report_kind: kind }),
        }),
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("persists the in-flight job id scoped to user and workspace, and clears it when the job finishes", async () => {
    window.localStorage.setItem("active_workspace_id", "42");
    render(<ReportsPageClient />);

    await openConfigureStep(/standard pdf/i);
    fireEvent.click(screen.getByRole("button", { name: /generate standard pdf/i }));

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(window.localStorage.getItem("signal.reportJob.v1.user-1.42")).toBeNull();
    });

    expect(fetchComplexReportStatus).toHaveBeenCalledWith("report-123", {
      Authorization: "Bearer token-123",
      "X-Workspace-Id": "42",
    });
  });

  it("resumes polling a stored in-flight job after a reload and downloads it", async () => {
    window.localStorage.setItem(
      "signal.reportJob.v1.user-1.default",
      JSON.stringify({ reportId: "report-123", kind: "standard" })
    );

    render(<ReportsPageClient />);

    await waitFor(() => {
      expect(fetchComplexReportStatus).toHaveBeenCalledWith("report-123", {
        Authorization: "Bearer token-123",
      });
    });
    await waitFor(() => {
      expect(downloadComplexReportPdfBlob).toHaveBeenCalledWith("report-123", {
        Authorization: "Bearer token-123",
      });
    });
    expect(window.localStorage.getItem("signal.reportJob.v1.user-1.default")).toBeNull();
  });

  it("does not resume a job stored for a different user", async () => {
    window.localStorage.setItem(
      "signal.reportJob.v1.someone-else.default",
      JSON.stringify({ reportId: "report-123", kind: "standard" })
    );

    render(<ReportsPageClient />);

    await waitFor(() => {
      expect(fetchWorkspaceProjects).toHaveBeenCalled();
    });
    expect(fetchComplexReportStatus).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("signal.reportJob.v1.someone-else.default")).not.toBeNull();
  });

  it("clears the stored job and surfaces the failure when the job fails", async () => {
    vi.mocked(fetchComplexReportStatus).mockResolvedValue({
      report_id: "report-123",
      status: "failed",
      download_url: null,
      error: "No completed audits matched the selected range",
    });
    window.localStorage.setItem(
      "signal.reportJob.v1.user-1.default",
      JSON.stringify({ reportId: "report-123", kind: "standard" })
    );

    render(<ReportsPageClient />);

    await waitFor(() => {
      expect(
        screen.getByText(/No completed audits matched the selected range/)
      ).toBeInTheDocument();
    });
    expect(window.localStorage.getItem("signal.reportJob.v1.user-1.default")).toBeNull();
  });

  it("shows an explicit expired state instead of a dead download", async () => {
    vi.mocked(fetchComplexReportStatus).mockResolvedValue({
      report_id: "report-123",
      status: "expired",
      download_url: null,
      error: null,
      error_detail: null,
    });

    render(<ReportsPageClient />);

    await openConfigureStep(/standard pdf/i);
    fireEvent.click(screen.getByRole("button", { name: /generate standard pdf/i }));

    await waitFor(() => {
      expect(screen.getByText(/expired/i)).toBeInTheDocument();
    });
  });

  it("does not queue a second job while one is running", async () => {
    vi.mocked(fetchComplexReportStatus).mockImplementation(() => new Promise(() => {}));

    render(<ReportsPageClient />);

    await openConfigureStep(/standard pdf/i);
    const generateButton = screen.getByRole("button", {
      name: /generate standard pdf/i,
    });
    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(generateComplexReportPdf).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(generateButton).toBeDisabled();
    });

    fireEvent.click(generateButton);
    expect(generateComplexReportPdf).toHaveBeenCalledTimes(1);
  });
});
