import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchProjectBotLogSummary,
  fetchProjectBotLogSources,
  uploadProjectBotLogFile,
  upsertProjectBotLogSource,
  MockBotLogApiError,
  getTokenMock,
} = vi.hoisted(() => {
  class HoistedBotLogApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
      this.name = "BotLogApiError";
    }
  }

  return {
    fetchProjectBotLogSummary: vi.fn(),
    fetchProjectBotLogSources: vi.fn(),
    uploadProjectBotLogFile: vi.fn(),
    upsertProjectBotLogSource: vi.fn(),
    MockBotLogApiError: HoistedBotLogApiError,
    getTokenMock: vi.fn().mockResolvedValue("token-123"),
  };
});

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    getToken: getTokenMock,
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/services/projectBotLogService", () => ({
  BotLogApiError: MockBotLogApiError,
  fetchProjectBotLogSummary: (...args: unknown[]) => fetchProjectBotLogSummary(...args),
  fetchProjectBotLogSources: (...args: unknown[]) => fetchProjectBotLogSources(...args),
  uploadProjectBotLogFile: (...args: unknown[]) => uploadProjectBotLogFile(...args),
  upsertProjectBotLogSource: (...args: unknown[]) => upsertProjectBotLogSource(...args),
}));

let ProjectBotLogAnalyzerPanel: React.ComponentType<{ projectId: string }>;

const baseSummaryPayload = {
  project_id: 42,
  generated_at: "2026-03-05T14:00:00.000Z",
  window_days: 30,
  latest_snapshot_date: "2026-03-05",
  no_data: false,
  degraded: false,
  degraded_reasons: [],
  totals: {
    total_hits: 1280,
    verified_hits: 1200,
    spoofed_hits: 80,
    error_4xx_hits: 42,
    error_5xx_hits: 11,
  },
  time_series: [
    { date: "2026-03-04", hits: 640, verified_hits: 600, spoofed_hits: 40 },
    { date: "2026-03-05", hits: 640, verified_hits: 600, spoofed_hits: 40 },
  ],
  bot_breakdown: [
    {
      bot_name: "GPTBot",
      hits: 900,
      verified_hits: 880,
      spoofed_hits: 20,
      error_4xx_hits: 20,
      error_5xx_hits: 5,
    },
    {
      bot_name: "PerplexityBot",
      hits: 380,
      verified_hits: 320,
      spoofed_hits: 60,
      error_4xx_hits: 22,
      error_5xx_hits: 6,
    },
  ],
  section_heatmap: [
    { section: "/blog/", hits: 800 },
    { section: "/products/", hits: 320 },
  ],
  spoofing_radar: [{ bot_name: "PerplexityBot", spoofed_hits: 60 }],
  ingestion_sources: [],
  latest_upload: null,
};

const baseSourcesPayload = {
  project_id: 42,
  items: [
    {
      id: 1,
      source_type: "manual_upload",
      display_name: "Manual",
      config: {},
      is_active: true,
      last_sync_at: null,
      last_status: "configured",
      last_error: null,
      updated_at: "2026-03-05T14:00:00.000Z",
    },
  ],
};

describe("ProjectBotLogAnalyzerPanel", () => {
  beforeAll(async () => {
    const panelModule = await import("@/components/dashboard/ProjectBotLogAnalyzerPanel");
    ProjectBotLogAnalyzerPanel = panelModule.default;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    getTokenMock.mockResolvedValue("token-123");
    fetchProjectBotLogSummary.mockResolvedValue(baseSummaryPayload);
    fetchProjectBotLogSources.mockResolvedValue(baseSourcesPayload);
    uploadProjectBotLogFile.mockResolvedValue({
      project_id: 42,
      upload_id: 11,
      status: "processed",
      bytes_processed: 1024,
      lines_processed: 3,
      bot_hits: 3,
      skipped_lines: 0,
      aggregate_rows: 2,
      summary_rows: 2,
      degraded: false,
      degraded_reasons: [],
    });
    upsertProjectBotLogSource.mockResolvedValue(baseSourcesPayload.items[0]);
  });

  it("shows plan lock state when API returns 402", async () => {
    const serviceModule = await import("@/services/projectBotLogService");
    fetchProjectBotLogSummary.mockRejectedValue(
      new serviceModule.BotLogApiError(
        402,
        "LLM Bot Log Analyzer requires Specialist or Executive."
      )
    );

    render(<ProjectBotLogAnalyzerPanel projectId="42" />);

    // SIGV2-1221: the plan is derived from `api_access`, the capability
    // `monitoring_router` gates this endpoint on, so the card states it in
    // the title and in the CTA instead of the plan-free "Upgrade Plan".
    expect(
      await screen.findByText("The AI bot log analyzer requires Specialist")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Upgrade to Specialist/i })).toBeInTheDocument();
  });

  it("renders empty-state CTA when summary has no data", async () => {
    fetchProjectBotLogSummary.mockResolvedValue({
      ...baseSummaryPayload,
      no_data: true,
      totals: {
        total_hits: 0,
        verified_hits: 0,
        spoofed_hits: 0,
        error_4xx_hits: 0,
        error_5xx_hits: 0,
      },
      bot_breakdown: [],
      section_heatmap: [],
      spoofing_radar: [],
    });

    render(<ProjectBotLogAnalyzerPanel projectId="42" />);

    expect(await screen.findByText("No AI bot crawl data yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Upload First Log/i })).toBeInTheDocument();
  });

  it("renders bot metrics and breakdown when data exists", async () => {
    render(<ProjectBotLogAnalyzerPanel projectId="42" />);

    expect(await screen.findByText("Total Bot Hits")).toBeInTheDocument();
    expect(screen.getByText("Bot Breakdown")).toBeInTheDocument();
    expect(screen.getByText("Section Heatmap")).toBeInTheDocument();
    expect(screen.getByText("GPTBot")).toBeInTheDocument();
    expect(screen.getAllByText("PerplexityBot").length).toBeGreaterThan(0);
  });
});
