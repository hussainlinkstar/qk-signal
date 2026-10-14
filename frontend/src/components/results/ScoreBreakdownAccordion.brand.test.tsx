import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import ScoreBreakdownAccordion from "./ScoreBreakdownAccordion";

const SEO_SUB_SCORES = [
  { key: "core_web_vitals", label: "core_web_vitals", score: 80, weight: 0.25 },
  { key: "technical_seo", label: "technical_seo", score: 70, weight: 0.2 },
  { key: "onpage_content", label: "onpage_content", score: 65, weight: 0.2 },
  { key: "eeat_trust", label: "eeat_trust", score: 75, weight: 0.2 },
  { key: "security_accessibility", label: "security_accessibility", score: 60, weight: 0.15 },
];

const BRAND_SEO_SUB_SCORES = [
  { key: "technical_seo", label: "technical_seo", score: 70, weight: 0.3 },
  { key: "onpage_content", label: "onpage_content", score: 65, weight: 0.25 },
  { key: "eeat_trust", label: "eeat_trust", score: 75, weight: 0.25 },
  { key: "security_accessibility", label: "security_accessibility", score: 60, weight: 0.2 },
];

describe("ScoreBreakdownAccordion brand-aware labels", () => {
  it("renders standard labels when isBrandWithoutUrl is false", () => {
    render(
      <ScoreBreakdownAccordion
        title="SEO Granular Breakdown"
        overallScore={70}
        subScores={SEO_SUB_SCORES}
        defaultOpen
        isBrandWithoutUrl={false}
      />
    );

    expect(screen.getByText("Core Web Vitals & Performance")).toBeInTheDocument();
    expect(screen.getByText("Technical SEO")).toBeInTheDocument();
    expect(screen.getByText("E-E-A-T & Trust Signals")).toBeInTheDocument();
  });

  it("renders brand-specific labels when isBrandWithoutUrl is true", () => {
    render(
      <ScoreBreakdownAccordion
        title="SEO Granular Breakdown"
        overallScore={70}
        subScores={BRAND_SEO_SUB_SCORES}
        defaultOpen
        isBrandWithoutUrl={true}
      />
    );

    expect(screen.getByText("Search Presence Signals")).toBeInTheDocument();
    expect(screen.getByText("E-E-A-T & Authority")).toBeInTheDocument();
    expect(screen.queryByText("Core Web Vitals & Performance")).not.toBeInTheDocument();
    expect(screen.queryByText("Technical SEO")).not.toBeInTheDocument();
  });

  it("defaults to standard labels when isBrandWithoutUrl is not provided", () => {
    render(
      <ScoreBreakdownAccordion
        title="Test"
        overallScore={50}
        subScores={SEO_SUB_SCORES}
        defaultOpen
      />
    );

    expect(screen.getByText("Core Web Vitals & Performance")).toBeInTheDocument();
  });

  it("returns null when subScores is empty", () => {
    const { container } = render(
      <ScoreBreakdownAccordion title="Empty" overallScore={0} subScores={[]} />
    );

    expect(container.innerHTML).toBe("");
  });
});
