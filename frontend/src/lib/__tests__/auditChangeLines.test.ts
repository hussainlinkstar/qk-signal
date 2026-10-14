import { describe, expect, it } from "vitest";

import { deriveAuditChangeLines } from "@/lib/auditChangeLines";
import type { AuditComparisonResponse } from "@/hooks/useAuditComparison";

const comparison = (overrides: Partial<AuditComparisonResponse> = {}): AuditComparisonResponse => ({
  audit_id: 1,
  has_previous: true,
  previous_audit_id: 0,
  previous_audit_date: "2026-02-19T10:00:00Z",
  scores: {
    overall: { current: 73, previous: 69, delta: 4, direction: "up" },
    seo: { current: 81, previous: 79, delta: 2, direction: "up" },
    geo: { current: 72, previous: 70, delta: 2, direction: "up" },
    aeo: { current: 66, previous: 62, delta: 4, direction: "up" },
  },
  sub_components: {},
  history: [],
  ...overrides,
});

describe("deriveAuditChangeLines", () => {
  it("returns nothing when there is no previous check", () => {
    expect(deriveAuditChangeLines(null)).toEqual([]);
    expect(deriveAuditChangeLines(comparison({ has_previous: false }))).toEqual([]);
  });

  it("returns nothing when the comparison carries no sub-component breakdown", () => {
    expect(deriveAuditChangeLines(comparison())).toEqual([]);
  });

  it("keeps only labelled components that moved past the backend's stable floor", () => {
    const lines = deriveAuditChangeLines(
      comparison({
        sub_components: {
          seo: {
            core_web_vitals: { current: 70, previous: 55, delta: 15, direction: "up" },
            technical_seo: { current: 68, previous: 67, delta: 1, direction: "stable" },
            onpage_content: { current: 61, previous: 61, delta: 0, direction: "stable" },
            future_component: { current: 40, previous: 10, delta: 30, direction: "up" },
          },
          aeo: {
            snippet_formatting: { current: 45, previous: 52, delta: -7, direction: "down" },
          },
        },
      })
    );

    expect(lines).toEqual([
      { key: "core_web_vitals", previous: 55, current: 70, delta: 15 },
      { key: "snippet_formatting", previous: 52, current: 45, delta: -7 },
    ]);
  });

  it("skips a component the plan gate removed from one side of the pair", () => {
    const lines = deriveAuditChangeLines(
      comparison({
        sub_components: {
          seo: {
            eeat_trust: { current: 70, previous: null, delta: null, direction: "stable" },
          },
        },
      })
    );

    expect(lines).toEqual([]);
  });

  it("orders by the size of the movement and caps the list", () => {
    const lines = deriveAuditChangeLines(
      comparison({
        sub_components: {
          seo: {
            core_web_vitals: { current: 60, previous: 55, delta: 5, direction: "up" },
            technical_seo: { current: 80, previous: 60, delta: 20, direction: "up" },
            onpage_content: { current: 50, previous: 60, delta: -10, direction: "down" },
            security_accessibility: { current: 70, previous: 67, delta: 3, direction: "up" },
          },
        },
      })
    );

    expect(lines.map((line) => line.key)).toEqual([
      "technical_seo",
      "onpage_content",
      "core_web_vitals",
    ]);
  });
});
