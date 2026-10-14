import { describe, expect, it } from "vitest";

import { defaultAuditTierForRole, ROLE_LABEL, ROLE_MODES, shownInMode } from "@/lib/roleMode";

describe("roleMode", () => {
  it("exposes the five canonical role modes", () => {
    expect(ROLE_MODES.length).toBe(5);
  });

  it("labels explorer as 'Just exploring'", () => {
    expect(ROLE_LABEL.explorer).toBe("Just exploring");
  });
});

describe("shownInMode", () => {
  it("marketer hides deep technical", () => {
    expect(shownInMode("technical", "marketer")).toBe(false);
    expect(shownInMode("recommendations", "marketer")).toBe(true);
  });

  it("specialist sees technical + aeo/geo", () => {
    expect(shownInMode("technical", "specialist")).toBe(true);
    expect(shownInMode("aeo", "specialist")).toBe(true);
  });

  it("agency sees portfolio + white_label, hides raw technical", () => {
    expect(shownInMode("portfolio", "agency")).toBe(true);
    expect(shownInMode("white_label", "agency")).toBe(true);
    expect(shownInMode("technical", "agency")).toBe(false);
  });

  it("enterprise sees multibrand + audit_trail", () => {
    expect(shownInMode("multibrand", "enterprise")).toBe(true);
    expect(shownInMode("audit_trail", "enterprise")).toBe(true);
  });
});

describe("defaultAuditTierForRole", () => {
  it("maps marketer to smart", () => {
    expect(defaultAuditTierForRole("marketer")).toBe("smart");
  });

  it("maps explorer to fast", () => {
    expect(defaultAuditTierForRole("explorer")).toBe("fast");
  });

  it("maps specialist to deep_judgment", () => {
    expect(defaultAuditTierForRole("specialist")).toBe("deep_judgment");
  });

  it("maps agency to smart", () => {
    expect(defaultAuditTierForRole("agency")).toBe("smart");
  });

  it("maps enterprise to deep_judgment", () => {
    expect(defaultAuditTierForRole("enterprise")).toBe("deep_judgment");
  });
});
