import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProjectProgressReportsClient from "@/components/dashboard/ProjectProgressReportsClient";
import {
  fetchProjectProgressReports,
  generateProjectProgressReport,
} from "@/services/workspaceService";

const getToken = vi.fn(async () => "token-123");

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    isSignedIn: true,
    getToken,
  }),
}));

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: () => ({
    latestAudit: {
      id: 501,
      created_at: "2026-03-02T10:00:00.000Z",
      full_report: {
        prioritized_actions: [
          {
            title: "Expand comparison pages with structured data",
            description: "Ship FAQ and comparison schema.",
            category: "Technical",
          },
        ],
      },
    },
  }),
}));

vi.mock("@/components/dashboard/AuditAnnotationThread", () => ({
  default: ({ title }: { title: string }) => <div>Thread: {title}</div>,
}));

vi.mock("@/services/workspaceService", () => ({
  fetchProjectProgressReports: vi.fn(),
  generateProjectProgressReport: vi.fn(),
}));

describe("ProjectProgressReportsClient", () => {
  it("renders saved report history and generates a preview on demand", async () => {
    vi.mocked(fetchProjectProgressReports).mockResolvedValue([
      {
        id: 9,
        project_id: 42,
        workspace_id: 1,
        report_month: "2026-02-01",
        period_start: "2026-02-01",
        period_end: "2026-03-01",
        generated_by: "automation",
        recipient_count: 2,
        email_sent_at: "2026-03-01T08:00:00.000Z",
        created_at: "2026-03-01T08:00:00.000Z",
        language: "en",
        expired: false,
        retention_days: 30,
        snapshot: {
          project: { name: "Northwind", domain_url: "https://northwind.example" },
          current_scores: { seo: 66, geo: 61, aeo: 64, overall: 64 },
          previous_scores: { seo: 44, geo: 42, aeo: 43, overall: 43 },
          delta: { seo: 22, geo: 19, aeo: 21, overall: 21 },
          highlights: ["SEO improved by 22.0 points"],
          remaining_issues: ["Expand comparison pages with structured data."],
        },
      },
    ]);
    vi.mocked(generateProjectProgressReport).mockResolvedValue({
      id: 10,
      project_id: 42,
      workspace_id: 1,
      report_month: "2026-03-01",
      period_start: "2026-03-01",
      period_end: "2026-04-01",
      generated_by: "manual",
      recipient_count: 0,
      email_sent_at: null,
      created_at: "2026-03-02T09:00:00.000Z",
      language: "en",
      expired: false,
      retention_days: 30,
      snapshot: {
        project: { name: "Northwind", domain_url: "https://northwind.example" },
        current_scores: { seo: 69, geo: 65, aeo: 67, overall: 67 },
        previous_scores: { seo: 66, geo: 61, aeo: 64, overall: 64 },
        delta: { seo: 3, geo: 4, aeo: 3, overall: 3.5 },
        highlights: ["SEO improved by 3.0 points"],
        remaining_issues: [],
      },
    });

    render(<ProjectProgressReportsClient />);

    expect((await screen.findAllByText("February 2026")).length).toBeGreaterThan(0);
    expect(screen.getByText(/Automated Progress Reports/i)).toBeInTheDocument();
    expect(screen.getByText(/SEO improved by 22\.0 points/i)).toBeInTheDocument();
    expect(screen.getByText(/Living Report Context/i)).toBeInTheDocument();
    expect(screen.getAllByText("English").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Thread: Expand comparison pages with structured data/i)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Generate Preview/i }));

    await waitFor(() => {
      expect(generateProjectProgressReport).toHaveBeenCalledWith(
        "42",
        { deliver_email: false },
        { Authorization: "Bearer token-123" }
      );
    });

    expect((await screen.findAllByText("March 2026")).length).toBeGreaterThan(0);
    expect(screen.getByText(/SEO improved by 3\.0 points/i)).toBeInTheDocument();
  });

  it("shows an expired badge when a stored report is outside retention", async () => {
    vi.mocked(fetchProjectProgressReports).mockResolvedValue([
      {
        id: 11,
        project_id: 42,
        workspace_id: 1,
        report_month: "2025-12-01",
        period_start: "2025-12-01",
        period_end: "2026-01-01",
        generated_by: "automation",
        recipient_count: 1,
        email_sent_at: "2026-01-02T08:00:00.000Z",
        created_at: "2026-01-02T08:00:00.000Z",
        language: "en",
        expired: true,
        retention_days: 30,
        snapshot: {
          project: { name: "Northwind", domain_url: "https://northwind.example" },
          current_scores: { seo: 62, geo: 58, aeo: 57, overall: 59 },
          previous_scores: { seo: 61, geo: 56, aeo: 54, overall: 57 },
          delta: { seo: 1, geo: 2, aeo: 3, overall: 2 },
          highlights: [],
          remaining_issues: [],
        },
      },
    ]);
    vi.mocked(generateProjectProgressReport).mockResolvedValue({
      id: 12,
      project_id: 42,
      workspace_id: 1,
      report_month: "2026-03-01",
      period_start: "2026-03-01",
      period_end: "2026-04-01",
      generated_by: "manual",
      recipient_count: 0,
      email_sent_at: null,
      created_at: "2026-03-02T09:00:00.000Z",
      language: "en",
      expired: false,
      retention_days: 30,
      snapshot: { project: { name: "Northwind", domain_url: "https://northwind.example" } },
    });

    render(<ProjectProgressReportsClient />);

    expect((await screen.findAllByText(/Report expired/i)).length).toBeGreaterThan(0);
  });
});
