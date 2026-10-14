import { describe, expect, it } from "vitest";

import { auditFormSchema } from "./auditFormSchema";

describe("auditFormSchema", () => {
  it("allows brand assessments without a target URL", () => {
    const result = auditFormSchema.safeParse({
      auditTargetType: "brand",
      url: "",
      targetName: "Acme",
      targetUrl: "",
      provider: "google",
      tier: "fast",
      language: "en",
      market: "",
      category: "",
      entities: [],
      entityInput: "",
      selectedModels: [],
    });

    expect(result.success).toBe(true);
  });

  it("still requires a target URL for website assessments", () => {
    const result = auditFormSchema.safeParse({
      auditTargetType: "website",
      url: "",
      targetName: "",
      targetUrl: "",
      provider: "google",
      tier: "fast",
      language: "en",
      market: "",
      category: "",
      entities: [],
      entityInput: "",
      selectedModels: [],
    });

    expect(result.success).toBe(false);
    expect(result.error?.issues.some((issue) => issue.path.join(".") === "targetUrl")).toBe(true);
  });
});
