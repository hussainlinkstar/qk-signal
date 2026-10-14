import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
}));

vi.mock("@/hooks/useJiraExportTracker", () => ({
  useJiraExportTracker: () => ({
    getTrackedExport: () => null,
    markExported: vi.fn(),
  }),
}));

vi.mock("@/services/ai/aiStrategicInsightsService", () => ({
  generateAiStrategicInsights: vi.fn().mockResolvedValue({
    geo_prompt_ideas: [],
    aeo_query_ideas: [],
  }),
}));

vi.mock("@/services/monitoringService", () => ({
  createVisibilityQuery: vi.fn(),
  deleteVisibilityQuery: vi.fn(),
  fetchVisibilityQueries: vi.fn().mockResolvedValue({ queries: [] }),
  fetchVisibilitySummary: vi.fn().mockResolvedValue({ rows: [] }),
  updateVisibilityQuery: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import GeoTab from "./GeoTab";

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const BASE_GEO_TAB_DATA = {
  trustSignalsScore: 60,
  citabilityScore: 55,
  entityMatchingScore: 70,
  technicalSeoScore: 45,
  scoreDetails: {
    local_authority_score: 50,
    citation_consistency_score: 60,
    relevance_score: 55,
  },
};

const GEO_RECOMMENDATIONS = ["Improve entity schema coverage", "Add structured local citations"];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GeoTab brand-mode rendering", () => {
  it("renders brand entity assessment when isBrandWithoutUrl is true", () => {
    render(
      <GeoTab
        geoScore={48}
        geoSummary="Brand entity signals indicate moderate GEO presence."
        geoTabData={BASE_GEO_TAB_DATA}
        geoRecommendations={GEO_RECOMMENDATIONS}
        isBrandWithoutUrl={true}
      />
    );

    expect(screen.getByText("Brand Entity AI Visibility Assessment")).toBeInTheDocument();
    expect(screen.getByText(/brand entity signals and search presence/)).toBeInTheDocument();
    expect(screen.getByText("48")).toBeInTheDocument();
    expect(
      screen.getByText("Brand entity signals indicate moderate GEO presence.")
    ).toBeInTheDocument();
    expect(screen.getByText("Entity Visibility Recommendations")).toBeInTheDocument();
    expect(screen.getByText("Improve entity schema coverage")).toBeInTheDocument();
  });

  it("does NOT render brand assessment in website mode", () => {
    render(
      <GeoTab
        geoScore={48}
        geoSummary="Website GEO summary."
        geoTabData={BASE_GEO_TAB_DATA}
        geoRecommendations={GEO_RECOMMENDATIONS}
        isBrandWithoutUrl={false}
      />
    );

    expect(screen.queryByText("Brand Entity AI Visibility Assessment")).not.toBeInTheDocument();
  });

  it("defaults isBrandWithoutUrl to false when not provided", () => {
    render(
      <GeoTab
        geoScore={48}
        geoSummary="Website GEO summary."
        geoTabData={BASE_GEO_TAB_DATA}
        geoRecommendations={GEO_RECOMMENDATIONS}
      />
    );

    expect(screen.queryByText("Brand Entity AI Visibility Assessment")).not.toBeInTheDocument();
  });

  it("renders empty recommendations gracefully in brand mode", () => {
    render(
      <GeoTab
        geoScore={48}
        geoSummary="Summary text."
        geoTabData={BASE_GEO_TAB_DATA}
        geoRecommendations={[]}
        isBrandWithoutUrl={true}
      />
    );

    expect(screen.getByText("Brand Entity AI Visibility Assessment")).toBeInTheDocument();
    expect(screen.queryByText("Entity Visibility Recommendations")).not.toBeInTheDocument();
  });
});
