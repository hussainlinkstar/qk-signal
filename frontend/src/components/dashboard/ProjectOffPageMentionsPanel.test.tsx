import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchOffPageMentionsSummary,
  fetchOffPageMentionsTrends,
  fetchOffPageMentionsFeed,
  getTokenMock,
} = vi.hoisted(() => ({
  fetchOffPageMentionsSummary: vi.fn(),
  fetchOffPageMentionsTrends: vi.fn(),
  fetchOffPageMentionsFeed: vi.fn(),
  getTokenMock: vi.fn().mockResolvedValue("token-123"),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: getTokenMock }),
}));

vi.mock("@/services/monitoringService", () => ({
  fetchOffPageMentionsSummary: (...args: unknown[]) => fetchOffPageMentionsSummary(...args),
  fetchOffPageMentionsTrends: (...args: unknown[]) => fetchOffPageMentionsTrends(...args),
  fetchOffPageMentionsFeed: (...args: unknown[]) => fetchOffPageMentionsFeed(...args),
}));

let ProjectOffPageMentionsPanel: React.ComponentType<{ projectId: string }>;

const summaryPayload = {
  project_id: 7,
  generated_at: "2026-03-05T18:00:00.000Z",
  window_days: 30,
  latest_snapshot_date: "2026-03-05",
  no_data: false,
  degraded: false,
  degraded_reasons: [],
  off_page_aeo_score: 68.45,
  trend_delta: -6.2,
  totals: {
    total_mentions: 22,
    positive_mentions: 12,
    neutral_mentions: 6,
    negative_mentions: 4,
    unique_domains: 5,
  },
  top_domains: [
    {
      domain: "reddit.com",
      mentions: 10,
      avg_authority_score: 100,
      avg_sentiment_score: 0.21,
    },
  ],
  actionable_advice: [
    {
      title: "Thread about enterprise GEO tools",
      priority: "high",
      source_domain: "reddit.com",
      message: "Add a clarifying reply with benchmark proof.",
      mention_url: "https://reddit.com/r/example/post/1",
    },
  ],
  latest_mentions: [],
};

const trendsPayload = {
  project_id: 7,
  days: 30,
  points: [
    {
      date: "2026-03-03",
      off_page_aeo_score: 70.2,
      total_mentions: 5,
      positive_mentions: 2,
      negative_mentions: 1,
    },
    {
      date: "2026-03-04",
      off_page_aeo_score: 69.4,
      total_mentions: 6,
      positive_mentions: 4,
      negative_mentions: 1,
    },
    {
      date: "2026-03-05",
      off_page_aeo_score: 68.45,
      total_mentions: 11,
      positive_mentions: 6,
      negative_mentions: 2,
    },
  ],
};

const feedPayload = [
  {
    id: 1,
    project_id: 7,
    source_type: "manual_import",
    source_domain: "reddit.com",
    mention_url: "https://reddit.com/r/example/post/1",
    external_id: "abc123",
    title: "Best enterprise GEO tools",
    snippet: "Qiko Signal is frequently recommended for enterprise GEO assessments.",
    published_at: "2026-03-05T10:00:00.000Z",
    discovered_at: "2026-03-05T10:00:00.000Z",
    sentiment_label: "positive",
    sentiment_score: 0.66,
    linked_keywords: ["enterprise geo"],
    entities: ["Qiko Signal"],
    authority_score: 100,
    action_recommendation: "Join discussion with case study.",
    analysis_status: "completed",
  },
];

describe("ProjectOffPageMentionsPanel", () => {
  beforeAll(async () => {
    const panelModule = await import("@/components/dashboard/ProjectOffPageMentionsPanel");
    ProjectOffPageMentionsPanel = panelModule.default;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    getTokenMock.mockResolvedValue("token-123");
    fetchOffPageMentionsSummary.mockResolvedValue(summaryPayload);
    fetchOffPageMentionsTrends.mockResolvedValue(trendsPayload);
    fetchOffPageMentionsFeed.mockResolvedValue(feedPayload);
  });

  it("shows plan lock state when API indicates Specialist requirement", async () => {
    fetchOffPageMentionsSummary.mockRejectedValue(
      new Error("Off-Page AEO Mentions Tracker requires Specialist or Executive.")
    );

    render(<ProjectOffPageMentionsPanel projectId="7" />);

    expect(
      await screen.findByText("Off-page mention tracking requires Specialist")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Upgrade to Specialist/i })).toBeInTheDocument();
  });

  it("shows empty state when no mention data exists", async () => {
    fetchOffPageMentionsSummary.mockResolvedValue({
      ...summaryPayload,
      no_data: true,
      totals: {
        total_mentions: 0,
        positive_mentions: 0,
        neutral_mentions: 0,
        negative_mentions: 0,
        unique_domains: 0,
      },
      top_domains: [],
      actionable_advice: [],
      latest_mentions: [],
    });

    render(<ProjectOffPageMentionsPanel projectId="7" />);

    expect(await screen.findByText("No Off-Page Mentions Yet")).toBeInTheDocument();
  });

  it("renders scorecards and feed when data exists", async () => {
    render(<ProjectOffPageMentionsPanel projectId="7" />);

    expect(await screen.findByText("Off-Page Answer Engine Index")).toBeInTheDocument();
    expect(screen.getByText("Top Domains")).toBeInTheDocument();
    expect(screen.getByText("Latest Mentions")).toBeInTheDocument();
    expect(screen.getByText("Best enterprise GEO tools")).toBeInTheDocument();
  });
});
