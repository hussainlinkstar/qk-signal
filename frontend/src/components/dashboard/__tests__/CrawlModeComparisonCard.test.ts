import { describe, it, expect } from "vitest";
import { deriveCrawlRecommendation } from "../CrawlModeComparisonCard";

describe("deriveCrawlRecommendation", () => {
  it("recommends bulk for small sites (<50 pages)", () => {
    const rec = deriveCrawlRecommendation(30, false);
    expect(rec.recommended).toBe("bulk");
    expect(rec.reason).toContain("fewer than 50 pages");
  });

  it("recommends smart for large sites (>500 pages)", () => {
    const rec = deriveCrawlRecommendation(800, false);
    expect(rec.recommended).toBe("smart");
    expect(rec.reason).toContain("500+");
  });

  it("recommends smart for repeat audits", () => {
    const rec = deriveCrawlRecommendation(200, true);
    expect(rec.recommended).toBe("smart");
    expect(rec.reason).toContain("tracking changes");
  });

  it("recommends smart for medium sites without prior crawl", () => {
    const rec = deriveCrawlRecommendation(200, false);
    expect(rec.recommended).toBe("smart");
  });

  it("recommends smart when total is null", () => {
    const rec = deriveCrawlRecommendation(null, false);
    expect(rec.recommended).toBe("smart");
  });

  it("boundary: exactly 50 pages → smart (not bulk)", () => {
    const rec = deriveCrawlRecommendation(50, false);
    expect(rec.recommended).toBe("smart");
  });

  it("boundary: exactly 49 pages → bulk", () => {
    const rec = deriveCrawlRecommendation(49, false);
    expect(rec.recommended).toBe("bulk");
  });
});
