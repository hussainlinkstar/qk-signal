/**
 * STORY-205: Verifies canonical_audit_payload.sample.json produces non-zero
 * values for ALL key dashboard metrics when normalised through the pipeline.
 */
import { describe, expect, it } from "vitest";
import {
  normalizeAuditHistoryPayload,
  type AuditHistoryPayload,
} from "@/lib/dashboardHistoryAdapters";
import { canonicalToDashboardAdapter, type CanonicalAuditReport } from "@/lib/reportAdapters";
import canonicalPayloadJson from "../../../../contracts/canonical_audit_payload.sample.json";

describe("STORY-205: Canonical → AuditResult reconciliation", () => {
  const historyPayload: AuditHistoryPayload[] = [
    { id: 1, status: "completed", full_report: canonicalPayloadJson },
  ];

  const audits = normalizeAuditHistoryPayload(historyPayload);

  it("normalizes exactly one audit from the canonical sample", () => {
    expect(audits).toHaveLength(1);
  });

  describe("AC-1: canonicalToDashboardAdapter maps all fields", () => {
    const audit = audits[0];

    it("SEO score is non-zero and matches sample", () => {
      expect(audit.scores.seo).toBe(81);
      expect(audit.seo.onpage).toBe(81);
      expect(audit.seo.performance).toBe(79);
      expect(audit.seo.indexing).toBe(80);
    });

    it("GEO visibility is non-zero and matches sample", () => {
      expect(audit.scores.geo).toBe(72);
      expect(audit.geo.visibility_index).toBe(72);
      expect(audit.geo.citation_share).toBe(44);
      expect(audit.geo.brand_anchor).toBe(38);
    });

    it("AEO answerability is non-zero and matches sample", () => {
      expect(audit.scores.aeo).toBe(66);
      expect(audit.aeo.answerability_score).toBe(66);
      expect(audit.aeo.extractable_pages).toBe(12);
    });

    it("AEO schema health and readability are preserved", () => {
      expect(audit.aeo.schema_health).toBeDefined();
      expect((audit.aeo.schema_health as Record<string, unknown>)?.score).toBe(74);
      expect(audit.aeo.schema_coverage?.coverage_percent).toBe(74);
      expect(audit.aeo.readability_score).toBe(0.73);
      expect(audit.aeo.readability_findings).toContain("Paragraphs exceed 120 words");
      expect(audit.aeo.rewrite_suggestions).toHaveLength(1);
    });

    it("competitor count is non-zero", () => {
      expect(audit.competitors.length).toBeGreaterThan(0);
      expect(audit.competitors[0].name).toBe("Competitor A");
      expect(audit.competitors[0].score).toBe(64);
    });

    it("entities are populated", () => {
      expect(audit.entities.length).toBeGreaterThan(0);
      expect(audit.entities).toContain("ExampleCo");
      expect(audit.entities).toContain("Acme");
    });

    it("overall score is present", () => {
      expect(audit.scores.overall).toBe(73);
    });

    it("site info is mapped", () => {
      expect(audit.site.url).toBe("https://example.com/");
      expect(audit.site.market).toBe("us");
      expect(audit.site.language).toBe("en");
    });

    it("metadata is mapped including version", () => {
      expect(audit.metadata.version).toBe("2.0");
      expect(audit.metadata.plan).toBe("plan_specialist");
      expect(audit.metadata.created_at).toBe("2026-01-01T00:00:00Z");
    });

    it("hallucination data is preserved", () => {
      expect(audit.hallucination).toBeDefined();
      expect(audit.hallucination?.flagged_claims).toBe(1);
      expect(audit.hallucination?.total_claims).toBe(2);
    });
  });

  describe("AC-4: DashboardModulePage receives non-zero scores", () => {
    const audit = audits[0];

    it("scores.seo, scores.geo, scores.aeo are all > 0 for DashboardModulePage fallback grid", () => {
      expect(audit.scores.seo).toBeGreaterThan(0);
      expect(audit.scores.geo).toBeGreaterThan(0);
      expect(audit.scores.aeo).toBeGreaterThan(0);
    });
  });

  describe("AC-5: Workspace tabs and dashboard read identical paths", () => {
    it("direct adapter call matches pipeline output", () => {
      const directResult = canonicalToDashboardAdapter(
        canonicalPayloadJson as unknown as CanonicalAuditReport
      );
      const pipelineResult = audits[0];

      expect(directResult.scores.seo).toBe(pipelineResult.scores.seo);
      expect(directResult.scores.geo).toBe(pipelineResult.scores.geo);
      expect(directResult.scores.aeo).toBe(pipelineResult.scores.aeo);
      expect(directResult.geo.visibility_index).toBe(pipelineResult.geo.visibility_index);
      expect(directResult.aeo.answerability_score).toBe(pipelineResult.aeo.answerability_score);
      expect(directResult.competitors.length).toBe(pipelineResult.competitors.length);
      expect(directResult.entities.length).toBe(pipelineResult.entities.length);
    });
  });
});
