import { describe, expect, it } from "vitest";

import { isTitleRedundantWithDescription } from "@/lib/recommendationTitle";

describe("isTitleRedundantWithDescription", () => {
  it("flags the ellipsis-truncated headline the backend derives from the description", () => {
    // Exactly what /api/audits/:id returns today: score_utils._finding_title
    // could not fit the first sentence in its 90-character budget, so it cut
    // the description at a word boundary and appended an ellipsis.
    const title =
      "The page lacks a clear value proposition that is easily understandable by generative\u2026";
    const description =
      "The page lacks a clear value proposition that is easily understandable by generative engines. A clear value proposition helps generative engines accurately represent the brand.";

    expect(isTitleRedundantWithDescription(title, description)).toBe(true);
  });

  it("flags a headline that only differs from the description by trailing punctuation", () => {
    expect(
      isTitleRedundantWithDescription(
        "Brand identity and value proposition are clear",
        "Brand identity and value proposition are clear."
      )
    ).toBe(true);
  });

  it("keeps a genuine headline that summarises rather than repeats", () => {
    expect(
      isTitleRedundantWithDescription(
        "Missing structured data",
        "The page lacks Organization schema, so engines cannot resolve the brand entity."
      )
    ).toBe(false);
  });

  it("keeps a headline whose wording only partially overlaps the description", () => {
    expect(
      isTitleRedundantWithDescription(
        "The page lacks a clear value proposition",
        "Generative engines cannot resolve what the brand sells, because the page lacks a clear value proposition."
      )
    ).toBe(false);
  });

  it("does not treat missing data as redundant", () => {
    expect(isTitleRedundantWithDescription("", "Some description")).toBe(false);
    expect(isTitleRedundantWithDescription("Some title", "")).toBe(false);
    expect(isTitleRedundantWithDescription(null, undefined)).toBe(false);
  });
});
