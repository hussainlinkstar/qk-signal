import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CompetitorsTab from "./CompetitorsTab";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

// ---------------------------------------------------------------------------
// SIGV2-1317: "How you compare" is the approved leaderboard, not a stack of
// cards.
//
// `Signal Competitors.html:167` renders this comparison as one table inside
// one card: a rank, the company, AIO, SEO, a visibility bar and how the row
// was measured. The build had four levels of card instead, with hardcoded
// English, 9px shouting capitals, `font-black` throughout, and amber
// dark-theme colours on a light panel.
//
// These assertions move with it: the same facts, read off the approved row.
// ---------------------------------------------------------------------------

const baseCompetitor = {
  name: "Rival One",
  score: 82,
  source: "SERP",
  confidence_score: 0.82,
  geo_visibility: 74,
  aeo_score: 71,
  entity_strength: 69,
  rank: 2,
};

describe("CompetitorsTab", () => {
  it("renders exploratory discovery rows without measured score cards", () => {
    render(
      <CompetitorsTab
        competitors={[
          {
            ...baseCompetitor,
            source: "SERP estimate",
            geo_visibility: 0,
            aeo_score: 0,
            entity_strength: 0,
            rank: 0,
          },
        ]}
        competitorSummary={{
          mode: "exploratory",
          message:
            "Competitor discovery is exploratory for this audit. Run tracked competitor audits to unlock measured AI visibility, SEO, and AI answers deltas.",
          benchmark: {
            rows: [
              {
                name: "Rival One",
                is_target: false,
                exploratory: true,
                measurement_source: "discovery_estimate",
              },
            ],
          },
        }}
      />
    );

    // A named-only competitor says so in its own cell, and shows no scores it
    // does not have. It used to print a paragraph of ours inside an amber box
    // sized for a dark theme.
    expect(
      screen.getByText(tEn("signalAuditReport.competitors.measuredDiscovery"))
    ).toBeInTheDocument();
    expect(screen.getByText(tEn("signalAuditReport.competitors.notMeasured"))).toBeInTheDocument();

    // No shouting, and none of our vocabulary.
    expect(screen.queryByText(/Discovery-only estimate/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Answer Engine Index")).not.toBeInTheDocument();
    expect(screen.queryByText(/CONF:/)).not.toBeInTheDocument();
  });

  it("renders measured benchmark cards for grounded competitors", () => {
    render(
      <CompetitorsTab
        competitors={[baseCompetitor]}
        competitorSummary={{
          mode: "grounded",
          benchmark: {
            rows: [
              {
                name: "Rival One",
                is_target: false,
                exploratory: false,
                measurement_source: "project_snapshot",
              },
            ],
          },
        }}
      />
    );

    expect(
      screen.getByText(tEn("signalAuditReport.competitors.measuredTracked"))
    ).toBeInTheDocument();

    // The approved columns, and the scores in them.
    expect(screen.getByText(tEn("signalAuditReport.competitors.colAio"))).toBeInTheDocument();
    expect(screen.getByText(tEn("signalAuditReport.competitors.colSeo"))).toBeInTheDocument();
    expect(
      screen.getByText(tEn("signalAuditReport.competitors.colVisibility"))
    ).toBeInTheDocument();
    expect(screen.getByText("71")).toBeInTheDocument();
    expect(screen.getByText("82")).toBeInTheDocument();
  });

  it("renders an upgrade lock notice when the competitor payload is sanitized", () => {
    render(
      <CompetitorsTab
        competitors={[]}
        competitorSummary={{}}
        lockedSection={{
          is_locked: true,
          required_plan: "plan_specialist",
          required_plan_label: "Specialist",
          detail: "Competitor benchmarks and discovered rivals are locked on the current plan.",
          lock_origin: "read",
        }}
      />
    );

    expect(
      screen.getByText(/Competitor analysis is locked on the current plan/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/Locked in API payload/i)).toBeInTheDocument();
    expect(screen.getByText("Specialist")).toBeInTheDocument();
    expect(screen.queryByText(/No Competitors Detected/i)).not.toBeInTheDocument();
  });

  it("says nothing came back, in the reader's words, when nothing did", () => {
    render(<CompetitorsTab competitors={[]} competitorSummary={{}} />);

    expect(screen.getByText(tEn("signalAuditReport.competitors.empty"))).toBeInTheDocument();
    // The old empty state was "No Competitors Detected" in shouting capitals
    // over "The generative engine did not identify primary competitors",
    // which is our vocabulary rather than a customer's.
    expect(screen.queryByText(/generative engine/i)).not.toBeInTheDocument();
  });

  it("draws no card inside the section's own card", () => {
    const { container } = render(
      <CompetitorsTab competitors={[baseCompetitor]} competitorSummary={{}} />
    );

    // The disclosure around this section is already the card. Anything in
    // here with a panel fill and a radius is a second one.
    const nested = container.querySelectorAll('[class*="bg-(--panel)"][class*="rounded-(--r)"]');
    expect(nested.length).toBe(0);
  });
});
