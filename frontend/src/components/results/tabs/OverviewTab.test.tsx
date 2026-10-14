import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import OverviewTab from "@/components/results/tabs/OverviewTab";
import { normalizeAuditReport } from "@/lib/reportAdapters";

// Keep the test focused on the two-pillar headline + AIO drilldown wiring by
// stubbing the heavy presentational children that OverviewTab composes.
vi.mock("@/components/results/DeepAnalysis", () => ({ default: () => null }));
vi.mock("@/components/results/IntegrityStatusBanner", () => ({ default: () => null }));
vi.mock("@/components/results/RecommendationsList", () => ({ default: () => null }));
vi.mock("@/components/results/ScoreBreakdownAccordion", () => ({ default: () => null }));
vi.mock("@/components/results/DetailedSignalList", () => ({ default: () => null }));
vi.mock("@/components/results/ScoreHistorySparkline", () => ({ default: () => null }));
// ScoreGauge echoes the pillar label as text; stub it so the pillar label
// assertions resolve to a single element (the PillarCard label).
vi.mock("@/components/results/ScoreGauge", () => ({ default: () => null }));
vi.mock("@/components/results/AioBreakdown", () => ({
  default: () => <div data-testid="aio-breakdown">AIO breakdown</div>,
}));
vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
}));

const CANONICAL_SCHEMA_VERSION = "2026-03-09";

const report = normalizeAuditReport({
  schema_version: CANONICAL_SCHEMA_VERSION,
  site: { url: "https://pillars.example" },
  seo: { onpage: 80 },
  geo: { visibility_index: 60 },
  aeo: { answerability_score: 40 },
  entities: { items: [] },
  competitors: [],
  scores: { seo: 80, aeo: 40, geo: 60 },
  metadata: {},
});

// A report variant that carries a deterministic Advisor plan so the Advisor
// panel renders (and can be gated). Mirrors the backend `metadata.advisor` shape.
const reportWithAdvisor = normalizeAuditReport({
  schema_version: CANONICAL_SCHEMA_VERSION,
  site: { url: "https://pillars.example" },
  seo: { onpage: 80 },
  geo: { visibility_index: 60 },
  aeo: { answerability_score: 40 },
  entities: { items: [] },
  competitors: [],
  scores: { seo: 80, aeo: 40, geo: 60 },
  metadata: {
    advisor: {
      schema_version: CANONICAL_SCHEMA_VERSION,
      actions: [{ rank: 1, action: "Add Organization schema", impact: "high", effort: "low" }],
    },
  },
});

const baseProps = {
  report,
  overallScore: 60,
  seoScore: 80,
  aeoScore: 40,
  geoScore: 60,
  performance: {},
  network: {},
  structuredDataDetected: undefined,
  seoStatus: undefined,
  scoreGroups: [],
  allRecommendations: [],
  aeoTabData: null,
  geoTabData: null,
  aeoPanel: <div data-testid="aeo-panel" />,
  geoPanel: <div data-testid="geo-panel" />,
};

describe("OverviewTab two-pillar headline", () => {
  it("renders exactly the SEO and AIO headline pillars for a marketer", () => {
    render(<OverviewTab {...baseProps} roleMode="marketer" />);

    expect(screen.getByText("SEO")).toBeInTheDocument();
    expect(screen.getByText("AIO")).toBeInTheDocument();
    expect(screen.getByText(/Click SEO or AIO to see the detailed breakdown/i)).toBeInTheDocument();
    // Raw headline gauges (AEO/GEO/Overall metric cards) are hidden for non-specialists.
    expect(screen.queryByText("Answer Readiness")).not.toBeInTheDocument();
    expect(screen.queryByText("AI Citation Share")).not.toBeInTheDocument();
  });

  it("reveals the AIO drilldown when the AIO pillar is clicked", () => {
    render(<OverviewTab {...baseProps} roleMode="marketer" />);

    expect(screen.queryByTestId("aio-breakdown")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("AIO"));

    expect(screen.getByTestId("aio-breakdown")).toBeInTheDocument();
  });

  it("navigates to the SEO tab when the SEO pillar is clicked", () => {
    const onNavigateToTab = vi.fn();
    render(<OverviewTab {...baseProps} roleMode="marketer" onNavigateToTab={onNavigateToTab} />);

    fireEvent.click(screen.getByText("SEO"));

    expect(onNavigateToTab).toHaveBeenCalledWith("seo");
  });

  it("keeps the raw SEO/AEO/GEO gauges available for specialists", () => {
    render(<OverviewTab {...baseProps} roleMode="specialist" />);

    expect(screen.getByText("Answer Readiness")).toBeInTheDocument();
    expect(screen.getByText("AI Citation Share")).toBeInTheDocument();
  });
});

describe("OverviewTab per-role pillar copy (Task 9.2)", () => {
  it("renders plain-language interpretation + next action for a marketer", () => {
    render(<OverviewTab {...baseProps} roleMode="marketer" />);

    // SEO pillar (score 80) → plain "~X of 10 relevant searches" framing, no raw codes/jargon.
    expect(screen.getByText(/You appear in ~\d+ of 10 relevant searches/i)).toBeInTheDocument();
    // Role-appropriate next action is shown alongside (once per pillar).
    expect(
      screen.getAllByText(/Focus on the few actions that lift visibility the most/i).length
    ).toBeGreaterThan(0);
    // No banned jargon leaks onto the surface.
    expect(screen.queryByText(/neural/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/market dominance/i)).not.toBeInTheDocument();
  });

  it("renders raw stat-first interpretation for a specialist", () => {
    render(<OverviewTab {...baseProps} roleMode="specialist" />);

    // Specialists get the raw numbers first: "SEO sits at X/100, against a healthy threshold...".
    expect(screen.getByText(/SEO sits at \d+\/100/i)).toBeInTheDocument();
    expect(
      screen.getAllByText(/Prioritise the highest-severity findings first/i).length
    ).toBeGreaterThan(0);
  });
});

describe("OverviewTab Score Distribution roll-up caption", () => {
  it("points back to the AIO pillar above so the per-axis gauges aren't read as a fourth, disconnected score", () => {
    render(
      <OverviewTab
        {...baseProps}
        roleMode="marketer"
        scoreGroups={[
          { label: "SEO Score", score: 80 },
          { label: "AI Visibility Score", score: 60 },
          { label: "AI Answers Index", score: 40 },
        ]}
      />
    );

    expect(
      screen.getByText(
        /AI Visibility Score and AI Answers Index roll up into your AIO score above/i
      )
    ).toBeInTheDocument();
  });

  it("omits the caption when there is no score data to show", () => {
    render(<OverviewTab {...baseProps} roleMode="marketer" scoreGroups={[]} />);

    expect(screen.queryByText(/roll up into your AIO score above/i)).not.toBeInTheDocument();
  });

  it("omits the caption for the unrelated legacy Citability/Entity Match score groups", () => {
    render(
      <OverviewTab
        {...baseProps}
        roleMode="marketer"
        scoreGroups={[
          { label: "Citability", score: 70 },
          { label: "Entity Match", score: 65 },
          { label: "Trust Signals", score: 80 },
          { label: "Technical SEO", score: 55 },
        ]}
      />
    );

    expect(screen.queryByText(/roll up into your AIO score above/i)).not.toBeInTheDocument();
  });
});

describe("OverviewTab value-ladder upsell gating", () => {
  it("blurs the Advisor panel by default (fail-safe: canSeeAdvisor omitted)", () => {
    render(<OverviewTab {...baseProps} report={reportWithAdvisor} roleMode="marketer" />);

    // The blurred upsell points at the Standard plan.
    expect(screen.getByText(/Available on Standard and above/i)).toBeInTheDocument();
  });

  it("renders the Advisor panel unlocked when canSeeAdvisor is true", () => {
    render(
      <OverviewTab {...baseProps} report={reportWithAdvisor} roleMode="marketer" canSeeAdvisor />
    );

    expect(screen.getByTestId("advisor-panel")).toBeInTheDocument();
    expect(screen.queryByText(/Available on Standard and above/i)).not.toBeInTheDocument();
  });

  // SIGV2-1168: the done-for-you execution offer was withdrawn - the panel
  // is presentational only and no approved mockup draws it - so the tab
  // shows neither the blurred teaser nor the unlocked panel, at any tier.
  it("renders no Done-for-you panel and no Executive upsell for it, at a tier that previously saw the teaser", () => {
    render(<OverviewTab {...baseProps} roleMode="marketer" />);

    expect(screen.queryByTestId("execution-panel")).not.toBeInTheDocument();
    expect(screen.queryByText(/Available on Executive and above/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Done for you/i)).not.toBeInTheDocument();
  });

  it("still renders no Execution panel when canSeeExecution is true", () => {
    render(<OverviewTab {...baseProps} roleMode="marketer" canSeeExecution />);

    expect(screen.queryByTestId("execution-panel")).not.toBeInTheDocument();
    // The rest of the value ladder is untouched.
    expect(screen.getByTestId("engine-panel")).toBeInTheDocument();
  });

  it("never gates live engine tracking on plan (SIGV2-1108)", () => {
    // The backend grants `has_live_engine_tracking` on every plan, so the
    // engine panel is presented as included with no upgrade prompt, on the
    // lowest plan as much as on Executive.
    render(<OverviewTab {...baseProps} roleMode="marketer" canSeeExecution />);

    expect(screen.getByTestId("engine-panel")).toBeInTheDocument();
    expect(screen.getByText("Live engine tracking")).toBeInTheDocument();
    expect(screen.queryByText("Live engine tracking requires Executive")).not.toBeInTheDocument();
  });
});
