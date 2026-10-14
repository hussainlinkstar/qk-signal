import { describe, expect, it } from "vitest";

import {
  buildCompletedAuditScheduleParams,
  normalizeAuditProviderKey,
  normalizeAuditRequestedTier,
  resolveCompletedAuditRoute,
} from "@/lib/auditRouting";

describe("auditRouting", () => {
  it("normalizes audit provider keys from provider ids and model names", () => {
    expect(normalizeAuditProviderKey("google")).toBe("google");
    expect(normalizeAuditProviderKey("gpt-5")).toBe("openai");
    expect(normalizeAuditProviderKey("claude-opus-4-6")).toBe("anthropic");
    expect(normalizeAuditProviderKey("unknown-model")).toBeNull();
  });

  it("normalizes requested tier aliases to canonical UI tiers", () => {
    expect(normalizeAuditRequestedTier("fast")).toBe("fast");
    expect(normalizeAuditRequestedTier("smart")).toBe("smart");
    expect(normalizeAuditRequestedTier("deep")).toBe("smart");
    expect(normalizeAuditRequestedTier("deep_judgment")).toBe("deep_judgment");
    expect(normalizeAuditRequestedTier("high confidence")).toBe("deep_judgment");
  });

  it("prefers billed provider metadata before model-name fallbacks", () => {
    expect(
      resolveCompletedAuditRoute({
        billingProvider: "anthropic",
        provider: "gpt-5",
        requestedTier: "deep_judgment",
      })
    ).toEqual({
      provider: "anthropic",
      tier: "deep_judgment",
    });
  });

  it("falls back to tier routing when completed audit metadata does not include a provider key", () => {
    expect(
      resolveCompletedAuditRoute({
        requestedTier: "deep_judgment",
      })
    ).toEqual({
      provider: "anthropic",
      tier: "deep_judgment",
    });
  });

  it("builds schedule params from completed audit metadata without drifting to google defaults", () => {
    expect(
      buildCompletedAuditScheduleParams(
        {
          schema_version: "canonical",
          url: "https://example.com",
          target: {
            type: "website",
            name: "Example",
            url: "https://example.com",
            metadata: {},
          },
          analysis: {},
          performance: {},
          network: {},
          warnings: [],
          metadata: {
            billing_provider: "anthropic",
            provider: "gpt-5",
            requested_tier: "deep_judgment",
            category: "Finance",
            market: "Romania",
            language: "fr",
            entities: ["Acme", "OpenAI"],
            selected_models: ["openai", "anthropic"],
          },
          seo: {},
          aeo: {},
          geo: {},
          scores: {},
          competitors: [],
          entities: [],
          technical_signals: {},
          hallucination: null,
        },
        "DEEP"
      )
    ).toEqual({
      provider: "anthropic",
      tier: "deep_judgment",
      category: "Finance",
      market: "Romania",
      language: "fr",
      entities: ["Acme", "OpenAI"],
      selected_models: ["openai", "anthropic"],
    });
  });
});
