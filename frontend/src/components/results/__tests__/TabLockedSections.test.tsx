import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { LockedAuditSection } from "@/types/auditResult";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "1" }),
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

// Mock heavy dependencies that these tabs use
vi.mock("@/services/monitoringService", () => ({
  createVisibilityQuery: vi.fn(),
  deleteVisibilityQuery: vi.fn(),
  fetchVisibilityQueries: vi.fn().mockResolvedValue([]),
  fetchVisibilitySummary: vi.fn().mockResolvedValue({ rows: [] }),
  updateVisibilityQuery: vi.fn(),
}));
vi.mock("@/services/ai/aiStrategicInsightsService", () => ({
  generateAiStrategicInsights: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/hooks/useJiraExportTracker", () => ({
  useJiraExportTracker: () => ({
    isExporting: false,
    exportToJira: vi.fn(),
    exportedItems: [],
    isExported: () => false,
    getTrackedExport: () => null,
  }),
}));

import AeoTab from "@/components/results/tabs/AeoTab";
import GeoTab from "@/components/results/tabs/GeoTab";

const LOCKED_SECTION: LockedAuditSection = {
  is_locked: true,
  capability_key: "has_semantic_graph_mapping",
  required_plan: "plan_specialist",
  required_plan_label: "Specialist",
  detail: "Semantic graph and schema coverage insights are locked on the current plan.",
  lock_origin: "read",
};

const GEO_LOCKED_SECTION: LockedAuditSection = {
  is_locked: true,
  capability_key: "has_brand_integrity_guardrails",
  required_plan: "plan_executive",
  required_plan_label: "Executive",
  detail: "Brand integrity and grounding guardrails are locked on the current plan.",
  lock_origin: "read",
};

describe("AeoTab locked section", () => {
  it("renders PlanLockNotice when lockedSection is locked", () => {
    render(
      <AeoTab
        aeoScore={72}
        aeoScoreEntries={[]}
        aeoEntityClarity=""
        aeoRecommendations={[]}
        lockedSection={LOCKED_SECTION}
      />
    );
    expect(
      screen.getByText("AI answers schema insights are locked on the current plan")
    ).toBeInTheDocument();
    expect(screen.getByText("Specialist")).toBeInTheDocument();
  });

  it("renders normal content when lockedSection is null", () => {
    render(
      <AeoTab
        aeoScore={72}
        aeoScoreEntries={[["schema_health", 80]]}
        aeoEntityClarity="Good entity clarity"
        aeoRecommendations={["Add FAQ schema"]}
        lockedSection={null}
      />
    );
    // Should show score, not lock notice
    expect(
      screen.queryByText("AI answers schema insights are locked on the current plan")
    ).not.toBeInTheDocument();
  });

  it("renders normal content when lockedSection is undefined", () => {
    render(
      <AeoTab aeoScore={72} aeoScoreEntries={[]} aeoEntityClarity="" aeoRecommendations={[]} />
    );
    expect(
      screen.queryByText("AI answers schema insights are locked on the current plan")
    ).not.toBeInTheDocument();
  });

  it("uses detail from lockedSection when available", () => {
    render(
      <AeoTab
        aeoScore={72}
        aeoScoreEntries={[]}
        aeoEntityClarity=""
        aeoRecommendations={[]}
        lockedSection={{
          ...LOCKED_SECTION,
          detail: "Custom lock detail message",
        }}
      />
    );
    expect(screen.getByText("Custom lock detail message")).toBeInTheDocument();
  });
});

describe("GeoTab locked section", () => {
  it("renders PlanLockNotice when lockedSection is locked", () => {
    render(
      <GeoTab
        geoScore={65}
        geoSummary=""
        geoTabData={null}
        geoRecommendations={[]}
        lockedSection={GEO_LOCKED_SECTION}
      />
    );
    expect(
      screen.getByText("AI visibility integrity insights are locked on the current plan")
    ).toBeInTheDocument();
    expect(screen.getByText("Executive")).toBeInTheDocument();
  });

  it("renders normal content when lockedSection is null", () => {
    render(
      <GeoTab
        geoScore={65}
        geoSummary="Good GEO summary"
        geoTabData={{}}
        geoRecommendations={["Improve citations"]}
        lockedSection={null}
      />
    );
    expect(
      screen.queryByText("AI visibility integrity insights are locked on the current plan")
    ).not.toBeInTheDocument();
  });

  it("renders normal content when lockedSection is undefined", () => {
    render(<GeoTab geoScore={65} geoSummary="" geoTabData={null} geoRecommendations={[]} />);
    expect(
      screen.queryByText("AI visibility integrity insights are locked on the current plan")
    ).not.toBeInTheDocument();
  });
});
