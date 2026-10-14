import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectTimelineClient from "@/components/dashboard/ProjectTimelineClient";
import { fetchProjectAudits } from "@/services/workspaceService";

const push = vi.fn();
const getToken = vi.fn(async () => "token-123");

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
  useRouter: () => ({ push }),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    isSignedIn: true,
    getToken,
  }),
}));

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 400 }}>{children}</div>
    ),
  };
});

vi.mock("@/services/workspaceService", () => ({
  fetchProjectById: vi.fn(async () => ({
    id: 42,
    name: "Northwind",
    domain_url: "https://northwind.example",
  })),
  fetchProjectTrends: vi.fn(async () => ({
    project_id: 42,
    period: "90d",
    granularity: "weekly",
    data_points: [
      {
        date: "2026-01-01",
        seo: 44,
        geo: 42,
        aeo: 43,
        overall: 43,
        volatility_score: 4.2,
        audit_count: 2,
        latest_audit_at: "2026-01-24T09:00:00.000Z",
      },
      {
        date: "2026-02-01",
        seo: 66,
        geo: 61,
        aeo: 64,
        overall: 64,
        volatility_score: 7.1,
        audit_count: 2,
        latest_audit_at: "2026-02-28T09:00:00.000Z",
      },
    ],
    summary: {
      first: null,
      latest: null,
      delta: { seo: 22, geo: 19, aeo: 21, overall: 21 },
      trend_direction: { seo: "up", geo: "up", aeo: "up", overall: "up" },
    },
  })),
  fetchProjectTrendComparison: vi.fn(async () => ({
    project_id: 42,
    period: "90d",
    current_period: {
      start: "2026-02-01T00:00:00.000Z",
      end: "2026-03-01T00:00:00.000Z",
      seo: 66,
      geo: 61,
      aeo: 64,
      overall: 64,
      audit_count: 2,
    },
    previous_period: {
      start: "2026-01-01T00:00:00.000Z",
      end: "2026-02-01T00:00:00.000Z",
      seo: 44,
      geo: 42,
      aeo: 43,
      overall: 43,
      audit_count: 2,
    },
    delta: { seo: 22, geo: 19, aeo: 21, overall: 21 },
    trend_direction: { seo: "up", geo: "up", aeo: "up", overall: "up" },
  })),
  fetchProjectAudits: vi.fn(async () => [
    {
      id: 500,
      project_id: 42,
      audit_type: "DEEP",
      url: "https://northwind.example",
      geo_score: 65,
      seo_score: 70,
      aeo_score: 68,
      status: "completed",
      created_at: "2026-02-28T09:00:00.000Z",
      full_report: null,
    },
  ]),
}));

describe("ProjectTimelineClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders trend intelligence controls and score labels", async () => {
    render(<ProjectTimelineClient />);

    expect(await screen.findByText(/Historical Trends/i)).toBeInTheDocument();
    expect(screen.getByText(/Northwind/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30D" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Weekly" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI Volatility" })).toBeInTheDocument();
    expect(screen.getByText("SEO vs previous period")).toBeInTheDocument();
    expect(screen.getByText("Recent checkpoints behind the trendline")).toBeInTheDocument();
    expect(screen.getAllByText("AI visibility").length).toBeGreaterThan(0);
    expect(screen.queryByText("GEO Vector")).not.toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /View Report/i })).toBeInTheDocument();
    });
  });

  it("preserves the project and URL when launching the initial audit", async () => {
    vi.mocked(fetchProjectAudits).mockResolvedValueOnce([]);

    render(<ProjectTimelineClient />);

    fireEvent.click(await screen.findByRole("button", { name: /Begin Initial Assessment/i }));

    expect(push).toHaveBeenCalledWith(
      "/dashboard/audit?projectId=42&url=https%3A%2F%2Fnorthwind.example"
    );
  });
});
