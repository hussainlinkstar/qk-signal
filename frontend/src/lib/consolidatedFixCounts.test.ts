import { describe, expect, it } from "vitest";

import { deriveRecommendations, normalizeLatestAuditReport } from "@/lib/deriveRecommendations";
import {
  getConsolidatedFixes,
  getDetailedAuditRecommendations,
  type CanonicalAuditReport,
} from "@/lib/reportAdapters";

// ---------------------------------------------------------------------------
// SIGV2-1193 — no two surfaces may disagree about how many fixes exist.
//
// This is the acceptance test for the whole ticket, and it exists because of
// one specific complaint: the Improve tab said 22 and the action plan said 10,
// for the same audit, and the difference read as a contradiction rather than
// as two data sets.
//
// The two paths below are the two real ones in the app, and they are not the
// same code path by accident:
//
//   * the action plan page and the audit report's overview read the RAW
//     `full_report` (`isAuditResult(raw) ? raw as CanonicalAuditReport`),
//   * the Improve tabs, the project overview's top three and the audit
//     report's fix rows read the NORMALIZED report
//     (`normalizeReportWithDiagnostics` -> `normalizeCanonicalReport`).
//
// Normalization used to drop `recommendations`, which is precisely why the two
// could never agree. If a future change drops it again, or adds a row source
// to one path only, this test fails instead of a customer finding it.
// ---------------------------------------------------------------------------

const CODE = "missing_canonical_url";

const RAW_REPORT = {
  schema_version: "2026-03-09",
  site: { url: "https://counts.example" },
  target: { type: "website", name: "Counts", url: "https://counts.example", metadata: {} },
  seo: {},
  geo: {},
  aeo: {},
  entities: { items: [] },
  competitors: [],
  scores: {
    seo: 72,
    aeo: 61,
    geo: 58,
    seo_breakdown: {
      penalties: [
        // Coded, and also raised by the action plan: one problem, one row.
        { reason: "Missing canonical URL", impact: -15, code: CODE },
        // Coded, raised only by the audit.
        { reason: "Missing meta description", impact: -9, code: "missing_meta_description" },
        // Uncoded: it can never be proven to be any plan entry's problem, so
        // it keeps its own row.
        { reason: "Some brand-new penalty reason", impact: -6 },
      ],
    },
    aeo_breakdown: {
      penalties: [{ reason: "Missing FAQPage schema", impact: -12, code: "missing_aeo_schema" }],
    },
  },
  // The same content at three stages of processing: the plan is built from the
  // items, the items from the suggestions. Only one stage is ever listed.
  suggestions: [
    {
      title: "Implement Canonical URL Tag on Homepage",
      action: "Add a canonical URL tag pointing at the homepage's preferred URL.",
      category: "Technical",
      problem_code: CODE,
    },
    {
      title: "Publish a comparison page",
      action: "Compare your plans against the two competitors buyers ask about.",
      category: "Content",
    },
    {
      title: "Dropped for want of grounding",
      action: "Nothing in the audit supports this.",
      category: "Content",
    },
  ],
  recommendations: {
    items: [
      {
        title: "Implement Canonical URL Tag on Homepage",
        action: "Add a canonical URL tag pointing at the homepage's preferred URL.",
        category: "Technical",
        estimated_effort: "low",
        expected_score_impact: { seo: 12, geo: null, aeo: null, overall: 12 },
        rationale: "Duplicate URLs split the page's signals.",
        grounded_by_findings: [`seo.penalty.${CODE}`],
        problem_code: CODE,
      },
      {
        title: "Publish a comparison page",
        action: "Compare your plans against the two competitors buyers ask about.",
        category: "Content",
        expected_score_impact: { seo: null, geo: 5, aeo: 4, overall: 5 },
        grounded_by_findings: ["seo.finding.3"],
      },
      {
        title: "Dropped for want of grounding",
        action: "Nothing in the audit supports this.",
        category: "Content",
        grounded_by_findings: [],
        derived_from: [],
      },
    ],
  },
  metadata: {
    created_at: "2026-10-05T10:00:00.000Z",
    advisor: {
      schema_version: "advisor-det-1",
      // The ungrounded candidate is absent: `require_grounding=True` dropped
      // it, and the consolidated list does not put it back.
      actions: [
        {
          rank: 1,
          title: "Implement Canonical URL Tag on Homepage",
          action: "Add a canonical URL tag pointing at the homepage's preferred URL.",
          impact: "high",
          effort: "low",
          grounded_by_findings: [`seo.penalty.${CODE}`],
          problem_code: CODE,
        },
        {
          rank: 2,
          title: "Publish a comparison page",
          action: "Compare your plans against the two competitors buyers ask about.",
          impact: "medium",
          grounded_by_findings: ["seo.finding.3"],
        },
      ],
      strategic_summary: null,
      metadata: { total_candidates: 3, actions_count: 2, dropped_ungrounded: 1 },
    },
  },
} as const;

/** The shape `useProjectLatestAudit` hands the project surfaces. */
const LATEST_AUDIT = {
  id: 700,
  status: "completed",
  url: "https://counts.example",
  seo_score: 72,
  aeo_score: 61,
  geo_score: 58,
  full_report: RAW_REPORT,
};

describe("consolidated fix counts (SIGV2-1193)", () => {
  // The raw path: the action plan page and the audit report's overview panel.
  const rawFixes = getConsolidatedFixes(RAW_REPORT as unknown as CanonicalAuditReport);
  // The normalized path: the Improve tabs, the project overview's top three,
  // the audit report's fix rows.
  const normalizedFixes = deriveRecommendations(LATEST_AUDIT);

  it("counts the same fixes on the raw and the normalized path", () => {
    expect(rawFixes.length).toBeGreaterThan(0);
    expect(normalizedFixes.length).toBe(rawFixes.length);
  });

  it("names the same fixes, in the same order, on both paths", () => {
    expect(normalizedFixes.map((fix) => fix.title)).toEqual(rawFixes.map((fix) => fix.title));
    expect(normalizedFixes.map((fix) => fix.rank)).toEqual(rawFixes.map((fix) => fix.rank));
  });

  it("rates a fix identically on both paths", () => {
    // The disagreement this replaces was not only about totals: the action
    // plan could show a measured band for a fix the Improve tab showed as
    // unrated, because normalization dropped the ratings behind it.
    expect(normalizedFixes.map((fix) => fix.impactLevel)).toEqual(
      rawFixes.map((fix) => fix.impactLevel)
    );
    expect(normalizedFixes.map((fix) => fix.effortLevel)).toEqual(
      rawFixes.map((fix) => fix.effortLevel)
    );
    expect(normalizedFixes.map((fix) => fix.sources)).toEqual(rawFixes.map((fix) => fix.sources));
  });

  it("folds the one problem both channels raised, and nothing else", () => {
    // 4 penalties + 2 plan actions, minus the one canonical URL problem both
    // raised. The ungrounded candidate stays dropped.
    expect(rawFixes).toHaveLength(5);
    expect(rawFixes.filter((fix) => fix.problemCode === CODE)).toHaveLength(1);
    expect(rawFixes.some((fix) => fix.title === "Dropped for want of grounding")).toBe(false);
    expect(rawFixes.some((fix) => fix.title === "Missing canonical URL")).toBe(false);
  });

  it("gives every row a source and every merged row both of its sources", () => {
    for (const fix of rawFixes) {
      expect(fix.sources.length).toBeGreaterThan(0);
    }
    const merged = rawFixes.find((fix) => fix.problemCode === CODE);
    expect(merged?.sources).toEqual(["action_plan", "audit_finding"]);
  });

  it("keeps the legacy adapter name pointed at the same list", () => {
    const report = normalizeLatestAuditReport(LATEST_AUDIT) as CanonicalAuditReport;
    expect(getDetailedAuditRecommendations(report)).toEqual(getConsolidatedFixes(report));
  });

  it("agrees with the engine-filtered subsets the detail pages count", () => {
    // The SEO and AIO Improve tabs count engine filters of this list, so a
    // row can be absent from a tab but never invented by one.
    const seo = normalizedFixes.filter((fix) => fix.engines.includes("SEO"));
    const aio = normalizedFixes.filter(
      (fix) => fix.engines.includes("AEO") || fix.engines.includes("GEO")
    );
    for (const subset of [seo, aio]) {
      expect(subset.length).toBeLessThanOrEqual(normalizedFixes.length);
      for (const fix of subset) {
        expect(normalizedFixes).toContain(fix);
      }
    }
    // Every row belongs to at least one of the two tabs, so neither total can
    // be larger than the list and nothing is unreachable from both.
    expect(new Set([...seo, ...aio]).size).toBe(normalizedFixes.length);
  });
});
