import { describe, expect, it } from "vitest";

import { resolveHistoryScores, resolveHistoryTargetFields } from "@/hooks/useWorkspaceHistory";

describe("resolveHistoryTargetFields", () => {
  it("prefers audit row target fields before nested report target data", () => {
    const resolved = resolveHistoryTargetFields({
      audit_target_type: "brand",
      target_name: "Lavan Studio",
      target_url: "https://lavan.ro",
      target_metadata: { category: "bridal" },
      url: "https://lavan.ro",
      full_report: {
        target: {
          type: "website",
          name: "Legacy Lavan",
          url: "https://legacy.lavan.ro",
          metadata: { category: "fashion" },
        },
        metadata: {
          audit_target_type: "website",
          target_name: "Legacy Lavan",
        },
      },
    });

    expect(resolved.auditTargetType).toBe("brand");
    expect(resolved.targetName).toBe("Lavan Studio");
    expect(resolved.targetUrl).toBe("https://lavan.ro");
    expect(resolved.targetMetadata).toEqual({ category: "bridal" });
  });
});

describe("resolveHistoryScores", () => {
  it("prefers normalized top-level history columns over nested report scores", () => {
    const resolved = resolveHistoryScores({
      geo_score: 72,
      seo_score: 70.67,
      aeo_score: 55,
      full_report: {
        scores: {
          seo: 78.4,
          geo: 79.71,
          aeo: 75,
        },
      },
    });

    expect(resolved).toEqual({
      seoScore: 70.67,
      geoScore: 72,
      aeoScore: 55,
      overallScore: 66,
    });
  });
});
