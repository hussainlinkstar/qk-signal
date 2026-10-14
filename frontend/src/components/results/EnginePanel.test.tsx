import React from "react";
import { readFileSync } from "node:fs";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EnginePanel from "@/components/results/EnginePanel";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const CONTROLLED_PANEL_COPY = "Measured across a controlled panel of leading AI models.";
const LIVE_PANEL_COPY = "Measured directly on the live consumer AI engines.";
// The forbidden, dishonest claim we must NEVER make.
const FORBIDDEN_CLAIM = /your exact .* ranking/i;
// Consumer products we must never name as measured engines outside this panel.
const CONSUMER_PRODUCTS = [
  "ChatGPT",
  "Gemini",
  "Claude",
  "Perplexity",
  "Grok",
  "DeepSeek",
  "Bing",
  "Copilot",
  "Meta AI",
];

describe("EnginePanel", () => {
  it("names the measured engines", () => {
    render(<EnginePanel />);
    const body = within(screen.getByTestId("engine-panel"));
    for (const name of ["ChatGPT", "Gemini", "Claude", "Perplexity", "Grok", "DeepSeek"]) {
      expect(body.getAllByText(name).length).toBeGreaterThan(0);
    }
  });

  it("uses honest LIVE labelling and renders exactly one panel body", () => {
    render(<EnginePanel />);
    expect(screen.getByText(LIVE_PANEL_COPY)).toBeInTheDocument();
    expect(screen.getByText("Live engine tracking")).toBeInTheDocument();
    // One real body, no blurred duplicate behind a gate.
    expect(screen.getAllByTestId("engine-panel")).toHaveLength(1);
    expect(screen.queryByText(CONTROLLED_PANEL_COPY)).not.toBeInTheDocument();
  });

  it("shows no plan gate: live engine tracking is included on every plan (SIGV2-1108)", () => {
    const { container } = render(<EnginePanel />);
    // The backend grants `has_live_engine_tracking` to all five plans, so an
    // upgrade prompt here would sell a capability the customer already has.
    expect(screen.queryByText("Live engine tracking requires Executive")).not.toBeInTheDocument();
    expect(screen.queryByText(/Available on Executive and above/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/instead of the controlled model panel/i)).not.toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(/upgrade/i);
    expect(screen.queryByRole("link", { name: /upgrade/i })).not.toBeInTheDocument();
  });

  it("never claims a user's exact ranking on a named engine", () => {
    const { container } = render(<EnginePanel />);
    expect(container.textContent ?? "").not.toMatch(FORBIDDEN_CLAIM);
  });

  it("never renders Bing or Copilot as measurable engines", () => {
    const { container } = render(<EnginePanel />);
    for (const banned of ["Bing", "Copilot"]) {
      expect(container.textContent ?? "").not.toContain(banned);
    }
  });

  it("labels the Claude row 'Anthropic' instead of the redundant 'Anthropic Claude'", () => {
    render(<EnginePanel />);
    expect(screen.queryByText("Anthropic Claude")).not.toBeInTheDocument();
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
  });
});

describe("engine-name claims on the surfaces changed for SIGNAL-1068", () => {
  const read = (path: string) => readFileSync(`${process.cwd()}/${path}`, "utf8");

  it("keeps Bing, Copilot and unmeasurable products out of the gate claim", () => {
    const gate = read("src/app/gate/page.tsx");
    for (const banned of [
      "ChatGPT",
      "Gemini",
      "Claude",
      "Perplexity",
      "Copilot",
      "Grok",
      "Bing",
      "DeepSeek",
      "Meta AI",
    ]) {
      expect(gate).not.toContain(banned);
    }
    expect(gate).toContain("a controlled panel of leading AI models");
  });

  it("keeps unmeasurable products and 'visibility analysis' titles out of the footer partner list", () => {
    const footer = read("src/components/Footer.tsx");
    for (const banned of ["Bing", "Copilot", "Perplexity", "Meta AI", "visibility analysis"]) {
      expect(footer).not.toContain(banned);
    }
  });

  it("keeps marketing metadata, JSON-LD and consumer product names out of the public layout", () => {
    const layout = read("src/app/(public)/layout.tsx");
    for (const banned of CONSUMER_PRODUCTS) {
      expect(layout).not.toContain(banned);
    }
    // The marketing chrome and copy were retired with WEB-1008; the group now
    // holds only public app pages and must not reintroduce marketing claims.
    for (const retired of [
      "controlled panel of leading AI models",
      "generators, critics, and judges",
      "JsonLd",
      "MarketingHeader",
      "alternates",
    ]) {
      expect(layout).not.toContain(retired);
    }
  });

  it("never attributes a report to a consumer product brand", async () => {
    const { resolveAuditModelConfig, resolvePipelineSteps } =
      await import("@/constants/auditModelMap");
    for (const provider of ["google", "openai", "anthropic", "xai", "deepseek"]) {
      const cfg = resolveAuditModelConfig(provider, "smart");
      expect(cfg.providerLabel).toBe("Controlled model panel");
      expect(cfg.displayLabel).toBe("Controlled model panel");
      expect(cfg.strengthsTooltip).not.toMatch(/reported as/i);
    }
    for (const step of resolvePipelineSteps("smart").steps) {
      expect(step.providerLabel).toBe("Controlled model panel");
    }
  });
});
