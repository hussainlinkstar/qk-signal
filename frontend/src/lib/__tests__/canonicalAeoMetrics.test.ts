/**
 * Integration test: verifies that the canonical_audit_payload sample
 * produces non-zero AEO metrics when normalised through the dashboard pipeline.
 */
import { describe, expect, it } from "vitest";
import type { AuditHistoryPayload } from "@/lib/dashboardHistoryAdapters";
import { normalizeAuditHistoryPayload } from "@/lib/dashboardHistoryAdapters";

// Inline representation of the canonical_audit_payload.sample.json contract.
const CANONICAL_PAYLOAD = {
  schema_version: "2026-03-09",
  site: { url: "https://example.com/", market: "us", language: "en" },
  seo: { onpage: 81, performance: 79, indexing: 80 },
  geo: { visibility_index: 72, citation_share: 44, brand_anchor: 38 },
  aeo: {
    answerability_score: 66,
    extractable_pages: 12,
    schema_health: { score: 74, coverage_by_type: { FAQPage: 0.8 } },
    schema_coverage: {
      coverage_percent: 74,
      coverage_by_type: { FAQPage: 0.8 },
      missing_high_impact_types: ["HowTo"],
    },
    readability_score: 0.73,
    readability_findings: ["Paragraphs exceed 120 words"],
    rewrite_suggestions: [
      { paragraph: "Long paragraph text", suggestion: "Split into shorter sentences", score: 0.62 },
    ],
  },
  entities: ["ExampleCo", "Acme"],
  competitors: [
    {
      name: "Competitor A",
      score: 64,
      source: "serp",
      confidence_score: 0.91,
      geo_visibility: 69,
      aeo_score: 61,
      entity_strength: 58,
      rank: 1,
    },
  ],
  suggestions: [
    { priority: 1, title: "Add FAQ schema", action: "Add FAQPage JSON-LD to key pages" },
  ],
  scores: { seo: 81, geo: 72, aeo: 66, overall: 73 },
  metadata: {
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    plan: "plan_specialist",
    version: "2.0",
    service_status: { ai_service: "ok" },
    service_errors: {},
    scores_available: true,
    audit_outcome: "completed",
    intent: "informational",
    query_type: "informational",
    technical_signals: {
      performance: { score: 79, lcp_ms: 2100, cls: 0.08 },
      network: {
        http_version: "HTTP/2",
        supports_http2: true,
        supports_http3: true,
        supports_http3_inferred: true,
      },
    },
  },
  hallucination: {
    threshold: 0.85,
    total_claims: 2,
    flagged_claims: 1,
    claims: [
      {
        claim_id: "claim-1",
        claim_text: "Example claim",
        matched_truth_key: "homepage_faq",
        truth_value: "Different answer",
        similarity_score: 0.42,
        hallucination: true,
        discrepancy_type: "factual_mismatch",
        severity: "high",
      },
    ],
    high_risk_discrepancies: [
      {
        claim_id: "claim-1",
        claim_text: "Example claim",
        matched_truth_key: "homepage_faq",
        truth_value: "Different answer",
        similarity_score: 0.42,
        hallucination: true,
        discrepancy_type: "factual_mismatch",
        severity: "high",
      },
    ],
  },
};

describe("Canonical Payload → AEO Dashboard Metrics", () => {
  it("produces non-zero AEO metrics from isAuditResult fast-path", () => {
    const historyPayload: AuditHistoryPayload[] = [
      { id: 1, status: "completed", full_report: CANONICAL_PAYLOAD },
    ];

    const audits = normalizeAuditHistoryPayload(historyPayload);
    expect(audits.length).toBe(1);
    const audit = audits[0];

    // Core Answer Engine Indexs
    expect(audit.scores.aeo).toBe(66);
    expect(audit.aeo.answerability_score).toBe(66);
    expect(audit.aeo.extractable_pages).toBe(12);

    // Schema health & coverage
    expect(audit.aeo.schema_health).toBeDefined();
    expect((audit.aeo.schema_health as Record<string, unknown>)?.score).toBe(74);
    expect(audit.aeo.schema_coverage).toBeDefined();
    expect(audit.aeo.schema_coverage?.coverage_percent).toBe(74);
    expect(audit.aeo.schema_coverage?.missing_high_impact_types).toContain("HowTo");

    // Readability
    expect(audit.aeo.readability_score).toBe(0.73);
    expect(audit.aeo.readability_findings).toContain("Paragraphs exceed 120 words");
    expect(audit.aeo.rewrite_suggestions?.length).toBe(1);
  });

  it("propagates AEO fields even through legacy coercion path", () => {
    // Remove fields that isAuditResult checks for, forcing the legacy coercion path.
    const legacyPayload = {
      ...CANONICAL_PAYLOAD,
      analysis: { aeo_score: 66 },
    };

    const historyPayload: AuditHistoryPayload[] = [
      { id: 2, status: "completed", full_report: legacyPayload },
    ];

    const audits = normalizeAuditHistoryPayload(historyPayload);
    expect(audits.length).toBe(1);
    const audit = audits[0];

    // AEO canonical fields should survive legacy coercion
    expect(audit.aeo.extractable_pages).toBe(12);
    expect(audit.aeo.schema_health).toBeDefined();
    expect(audit.aeo.schema_coverage?.coverage_percent).toBe(74);
    expect(audit.aeo.readability_score).toBe(0.73);
  });
});
