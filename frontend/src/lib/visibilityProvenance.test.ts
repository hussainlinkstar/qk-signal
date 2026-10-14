import { describe, expect, it } from "vitest";

import { engineProvenance, provenanceByProvider } from "@/lib/visibilityProvenance";
import type {
  VisibilityProviderResult,
  VisibilitySummaryResponse,
  VisibilityProvider,
} from "@/types/monitoring";

function cell(
  provider: VisibilityProvider,
  over: Partial<VisibilityProviderResult> = {}
): VisibilityProviderResult {
  return {
    provider,
    status: "cited",
    batch_status: "succeeded",
    score: 42,
    score_breakdown: null,
    last_checked_at: "2026-10-10T09:00:00Z",
    citations_found: 1,
    presence: { state: "domain_citation", live_measured: true, reason: null },
    engine_source: "openrouter_live",
    model: "google/gemini-2.5-pro",
    ...over,
  };
}

function summary(results: VisibilityProviderResult[]): VisibilitySummaryResponse {
  return {
    queries: [{ results } as VisibilitySummaryResponse["queries"][number]],
  } as VisibilitySummaryResponse;
}

describe("engineProvenance", () => {
  it("reports live when the answer came from the named engine", () => {
    expect(engineProvenance([cell("google")])).toBe("live");
  });

  it("reports fallback when the answer came from the stand-in panel", () => {
    expect(
      engineProvenance([
        cell("google", {
          engine_source: "bedrock_proxy",
          model: "qwen.qwen3-235b-a22b-2507-v1:0",
          presence: { state: "domain_citation", live_measured: false, reason: null },
        }),
      ])
    ).toBe("fallback");
  });

  it("reports mixed when one engine has both live and fallback answers", () => {
    expect(
      engineProvenance([
        cell("google"),
        cell("google", {
          engine_source: "bedrock_proxy",
          presence: { state: "domain_citation", live_measured: false, reason: null },
        }),
      ])
    ).toBe("mixed");
  });

  it("falls back to presence.live_measured when engine_source is absent", () => {
    expect(
      engineProvenance([
        cell("google", {
          engine_source: null,
          presence: { state: "measured_absent", live_measured: false, reason: null },
        }),
      ])
    ).toBe("fallback");
  });

  it("treats the backend's own mixed marker as mixed", () => {
    expect(engineProvenance([cell("google", { engine_source: "mixed" })])).toBe("mixed");
  });

  // A cell we never measured carries no provenance, and reporting one would be
  // the same class of defect as reporting an unmeasured absence as an absence.
  it("reports unmeasured for pending, failed and explicitly unmeasured cells", () => {
    expect(engineProvenance([cell("google", { status: "pending" })])).toBe("unmeasured");
    expect(engineProvenance([cell("google", { status: "failed" })])).toBe("unmeasured");
    expect(
      engineProvenance([
        cell("google", {
          presence: { state: "unmeasured", live_measured: false, reason: "pending" },
        }),
      ])
    ).toBe("unmeasured");
  });

  it("reports unmeasured for an empty cell list", () => {
    expect(engineProvenance([])).toBe("unmeasured");
  });

  // A cell from a payload predating the provenance fields says nothing either
  // way, so it must not be counted as a live measurement.
  it("reports unmeasured when neither engine_source nor presence is present", () => {
    expect(engineProvenance([cell("google", { engine_source: null, presence: null })])).toBe(
      "unmeasured"
    );
  });
});

describe("provenanceByProvider", () => {
  it("groups each engine's cells independently", () => {
    const result = provenanceByProvider(
      summary([
        cell("google"),
        cell("perplexity", {
          engine_source: "bedrock_proxy",
          presence: { state: "measured_absent", live_measured: false, reason: null },
        }),
        cell("openai", { status: "pending" }),
      ])
    );

    expect(result).toEqual({
      google: "live",
      perplexity: "fallback",
      openai: "unmeasured",
    });
  });

  it("returns an empty map when there are no queries", () => {
    expect(provenanceByProvider({ queries: [] } as unknown as VisibilitySummaryResponse)).toEqual(
      {}
    );
  });
});
