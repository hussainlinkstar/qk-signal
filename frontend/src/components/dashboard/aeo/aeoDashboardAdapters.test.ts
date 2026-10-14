import { describe, expect, it } from "vitest";
import {
  buildAnswerabilityFunnelData,
  mapAeoTrustworthinessTrendToMetricSeries,
  resolveTrustworthinessSignalCoverage,
} from "@/components/dashboard/aeo/aeoDashboardAdapters";

describe("aeoDashboardAdapters", () => {
  it("builds funnel data from AEO site stats", () => {
    const data = buildAnswerabilityFunnelData(
      {
        site_id: 2,
        audit_count: 10,
        answer_dominance: {
          site_primary_count: 4,
          competitor_primary_count: 3,
          unknown_count: 3,
          site_primary_share: 57,
          competitor_primary_share: 43,
          site_primary_share_total: 40,
          competitor_primary_share_total: 30,
          unknown_share_total: 30,
        },
        top_performing_queries: [],
        answer_failure_reasons: [],
        schema_health: {
          avg_score: 78,
          healthy_audits: 8,
          issue_count: 5,
          coverage_percent: 100,
          coverage_by_type: {},
          missing_high_impact_types: [],
          high_impact_blockers: [],
        },
        competitor_benchmark: {
          site_avg_aeo_score: 74,
          competitor_avg_aeo_score: 68,
          score_gap: 6,
          competitor_count: 1,
        },
        query_category_breakdown: [],
        trustworthiness_trend: [],
        trustworthiness_signal_coverage: 0.6,
        readability_insights: {
          avg_readability_score: null,
          low_readability_audits: 0,
          findings: [],
          top_rewrite_suggestions: [],
        },
        authority_index: {
          value: 0,
          components: { trustworthiness: 0, answer_dominance: 0, schema_health: 0, readability: 0 },
          confidence: 0,
        },
        authority_index_trend: [],
        query_benchmark: {
          site_id: 2,
          site_domain: "example.com",
          competitor_count: 0,
          queries: [],
        },
      },
      3,
      2
    );

    expect(data).toEqual({
      totalAudits: 10,
      aiReadablePages: 10,
      directAnswerHits: 4,
      directAnswerHitsShareTotal: 40,
    });
  });

  it("falls back to assessment history values when site stats are missing", () => {
    const data = buildAnswerabilityFunnelData(null, 5, 3);

    expect(data).toEqual({
      totalAudits: 5,
      aiReadablePages: 3,
      directAnswerHits: 3,
      directAnswerHitsShareTotal: 60,
    });
  });

  it("maps and sorts trustworthiness trend values and drops missing-signal points", () => {
    const series = mapAeoTrustworthinessTrendToMetricSeries([
      { date: "2026-01-12", score: 71, audit_count: 4, signal_coverage: 0.75 },
      { date: "2026-01-05", score: null, audit_count: 2, signal_coverage: 0 },
      { date: "2026-01-19", score: 83, audit_count: 3, signal_coverage: 1 },
    ]);

    expect(series).toEqual([
      { date: "2026-01-12", value: 71, secondaryValue: 4, signalCoverage: 0.75 },
      { date: "2026-01-19", value: 83, secondaryValue: 3, signalCoverage: 1 },
    ]);
  });

  it("resolves trustworthiness signal coverage from aggregate or trend data", () => {
    expect(
      resolveTrustworthinessSignalCoverage({
        site_id: 2,
        audit_count: 3,
        answer_dominance: {
          site_primary_count: 1,
          competitor_primary_count: 1,
          unknown_count: 1,
          site_primary_share: 50,
          competitor_primary_share: 50,
          site_primary_share_total: 33.33,
          competitor_primary_share_total: 33.33,
          unknown_share_total: 33.34,
        },
        top_performing_queries: [],
        answer_failure_reasons: [],
        schema_health: {
          avg_score: 70,
          healthy_audits: 2,
          issue_count: 1,
          coverage_percent: 100,
          coverage_by_type: {},
          missing_high_impact_types: [],
          high_impact_blockers: [],
        },
        competitor_benchmark: {
          site_avg_aeo_score: 74,
          competitor_avg_aeo_score: 68,
          score_gap: 6,
          competitor_count: 1,
        },
        query_category_breakdown: [],
        trustworthiness_trend: [
          { date: "2026-01-12", score: 71, audit_count: 4, signal_coverage: 0.75 },
        ],
        trustworthiness_signal_coverage: 0.5,
        readability_insights: {
          avg_readability_score: null,
          low_readability_audits: 0,
          findings: [],
          top_rewrite_suggestions: [],
        },
        authority_index: {
          value: 0,
          components: { trustworthiness: 0, answer_dominance: 0, schema_health: 0, readability: 0 },
          confidence: 0,
        },
        authority_index_trend: [],
        query_benchmark: {
          site_id: 2,
          site_domain: "example.com",
          competitor_count: 0,
          queries: [],
        },
      })
    ).toBe(0.5);

    expect(
      resolveTrustworthinessSignalCoverage({
        site_id: 2,
        audit_count: 3,
        answer_dominance: {
          site_primary_count: 1,
          competitor_primary_count: 1,
          unknown_count: 1,
          site_primary_share: 50,
          competitor_primary_share: 50,
          site_primary_share_total: 33.33,
          competitor_primary_share_total: 33.33,
          unknown_share_total: 33.34,
        },
        top_performing_queries: [],
        answer_failure_reasons: [],
        schema_health: {
          avg_score: 70,
          healthy_audits: 2,
          issue_count: 1,
          coverage_percent: 100,
          coverage_by_type: {},
          missing_high_impact_types: [],
          high_impact_blockers: [],
        },
        competitor_benchmark: {
          site_avg_aeo_score: 74,
          competitor_avg_aeo_score: 68,
          score_gap: 6,
          competitor_count: 1,
        },
        query_category_breakdown: [],
        trustworthiness_trend: [
          { date: "2026-01-12", score: 71, audit_count: 4, signal_coverage: 0.25 },
          { date: "2026-01-19", score: null, audit_count: 2, signal_coverage: 0.75 },
        ],
        trustworthiness_signal_coverage: null,
        readability_insights: {
          avg_readability_score: null,
          low_readability_audits: 0,
          findings: [],
          top_rewrite_suggestions: [],
        },
        authority_index: {
          value: 0,
          components: { trustworthiness: 0, answer_dominance: 0, schema_health: 0, readability: 0 },
          confidence: 0,
        },
        authority_index_trend: [],
        query_benchmark: {
          site_id: 2,
          site_domain: "example.com",
          competitor_count: 0,
          queries: [],
        },
      })
    ).toBe(0.5);
  });
});
