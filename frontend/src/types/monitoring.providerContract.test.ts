import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { PROVIDER_COLORS } from "@/components/dashboard/VisibilityTrendChart";
import {
  VISIBILITY_PROVIDER_LABELS,
  offeredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";
import {
  OFFERED_VISIBILITY_PROVIDERS,
  VISIBILITY_PROVIDERS,
  WITHDRAWN_VISIBILITY_PROVIDERS,
} from "@/types/monitoring";

/**
 * The frontend's visibility provider vocabulary must equal the backend's.
 *
 * SIGV2-1163: it did not. The backend sends `meta` and has no `meta_ai` key at
 * all, while the frontend keyed this engine as `meta_ai` in four places, with
 * no normalisation anywhere - so a real `meta` row from `provider_breakdown`
 * missed the label map, the chart colour and the logo map at once, and the AIO
 * by-engine tab would have rendered the raw string `meta` with no icon. That is
 * a display bug that only appears the moment Meta visibility data lands, which
 * is exactly the kind of drift a test has to catch instead of a reader.
 *
 * The backend's list is not importable from here (different language, and the
 * frontend build must not reach into `backend/`), so the comparison is against
 * a committed copy of the backend vocabulary in
 * `contracts/visibility_providers.json`.
 *
 * HOW THE FIXTURE IS KEPT IN STEP - both halves are needed, neither is
 * optional:
 *   1. `backend/tests/test_visibility_provider_contract.py` asserts the
 *      fixture equals `SUPPORTED_VISIBILITY_PROVIDERS`,
 *      `VISIBILITY_PROVIDER_LABELS`, `LIVE_MEASURABLE_PROVIDERS` and the
 *      per-plan `allowed_providers`. Add a provider to the backend and backend
 *      CI fails until the fixture records it.
 *   2. This test then fails until the frontend handles the newly recorded key.
 * So the fixture cannot drift from the backend, and the frontend cannot drift
 * from the fixture. `contracts/**` is in both of CI's path filters for the same
 * reason: a PR that only touches the backend and the fixture still has to run
 * frontend CI, or half the loop sleeps.
 *
 * KEYS and label strings are both compared (SIGV2-1161): the frontend shows
 * the backend's consumer engine names, and an earlier version that named
 * Bedrock models instead mislabelled three providers outright, which is
 * exactly the drift this file exists to catch.
 */
const contractPath = path.resolve(__dirname, "../../../contracts/visibility_providers.json");
const contract = JSON.parse(readFileSync(contractPath, "utf8")) as {
  providers: string[];
  offered: string[];
  withdrawn: Record<string, string>;
  labels: Record<string, string>;
  live_measurable: string[];
  live_unavailable: Record<string, string>;
};

const sorted = (values: readonly string[]) => [...values].sort();

describe("the frontend's visibility provider keys match the backend's", () => {
  it("has a committed backend vocabulary to compare against", () => {
    expect(contract.providers.length).toBeGreaterThan(0);
    expect(sorted(Object.keys(contract.labels))).toEqual(sorted(contract.providers));
  });

  it("declares exactly the provider keys the backend can send", () => {
    expect(sorted(VISIBILITY_PROVIDERS)).toEqual(sorted(contract.providers));
  });

  it("carries no key the backend never sends", () => {
    const unknown = VISIBILITY_PROVIDERS.filter(
      (provider) => !contract.providers.includes(provider)
    );
    expect(unknown).toEqual([]);
    // The specific regression: `meta_ai` is not a backend value and must not
    // come back anywhere in the frontend's provider vocabulary.
    expect(VISIBILITY_PROVIDERS as readonly string[]).not.toContain("meta_ai");
    expect(Object.keys(VISIBILITY_PROVIDER_LABELS)).not.toContain("meta_ai");
    expect(Object.keys(PROVIDER_COLORS)).not.toContain("meta_ai");
  });

  it("is missing no key the backend does send", () => {
    const missing = contract.providers.filter(
      (provider) => !(VISIBILITY_PROVIDERS as readonly string[]).includes(provider)
    );
    expect(missing).toEqual([]);
  });

  // Every surface that keys off a provider has to resolve every provider. The
  // label map and the chart colour map are the two that silently produced
  // `undefined` for `meta`.
  it("shows every backend provider the backend's own label", () => {
    // SIGV2-1161: the strings are compared, not just the keys. The frontend
    // labels are the consumer engine names the backend defines; renaming a
    // provider to a model name is a customer-visible falsehood, not a style
    // choice.
    expect(VISIBILITY_PROVIDER_LABELS).toEqual(contract.labels);
  });

  it("gives every backend provider a chart colour", () => {
    expect(sorted(Object.keys(PROVIDER_COLORS))).toEqual(
      sorted([...contract.providers, "overall"])
    );
    for (const provider of contract.providers) {
      expect(PROVIDER_COLORS[provider as keyof typeof PROVIDER_COLORS]).toBeTruthy();
    }
  });

  // The engines the audit-start Model selection section names are the live
  // measurable ones; Copilot (`bing`) was proxy-only and stayed out
  // (SIGV2-1036) before being withdrawn from the product entirely
  // (SIGV2-1215).
  it("records which engines the backend can measure live", () => {
    expect(sorted(contract.live_measurable)).toEqual(
      sorted(contract.providers.filter((provider) => provider !== "bing"))
    );
    expect(Object.keys(contract.live_unavailable)).toEqual(["bing"]);
  });

  // SIGV2-1215: the vocabulary and the offer are different lists. The frontend
  // keeps every key so a recorded row still resolves to a label, and renders
  // only the offered ones.
  it("declares the same withdrawn engines the backend recorded", () => {
    expect(sorted(WITHDRAWN_VISIBILITY_PROVIDERS)).toEqual(sorted(Object.keys(contract.withdrawn)));
    expect(sorted(OFFERED_VISIBILITY_PROVIDERS)).toEqual(sorted(contract.offered));
    for (const provider of WITHDRAWN_VISIBILITY_PROVIDERS) {
      // Kept in the vocabulary and in the label map on purpose: a withdrawal
      // hides the engine, it does not erase its history.
      expect(VISIBILITY_PROVIDERS as readonly string[]).toContain(provider);
      expect(Object.keys(VISIBILITY_PROVIDER_LABELS)).toContain(provider);
      expect(OFFERED_VISIBILITY_PROVIDERS as readonly string[]).not.toContain(provider);
    }
  });

  it("drops a withdrawn engine from any list a surface is about to render", () => {
    expect(offeredVisibilityProviders(["bing", "google", "openai"])).toEqual(["google", "openai"]);
    // A list of nothing but withdrawn engines renders nothing, rather than
    // falling back to showing them.
    expect(offeredVisibilityProviders(["bing"])).toEqual([]);
    expect(offeredVisibilityProviders([])).toEqual([]);
  });
});
