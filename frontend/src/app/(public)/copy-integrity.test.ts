import { describe, expect, it } from "vitest";

import { codeSamples } from "@/app/(app)/dashboard/developer/content";

// The marketing pages and their pricing cards were retired along with the
// other duplicate Signal marketing pages; see WEB-1008. The remaining check
// here guards copy that is still live.

describe("public copy integrity", () => {
  it("renders copy-paste API examples against the real same-origin public API", () => {
    for (const sample of Object.values(codeSamples)) {
      expect(sample).toContain("https://qiko.ai/signal/api/v1/external/audit");
      expect(sample).not.toContain("http://localhost:8000");
      expect(sample).not.toContain("/api/v1/api/v1");
    }
  });
});
