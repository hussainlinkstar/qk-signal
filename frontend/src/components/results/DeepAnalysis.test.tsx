import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DeepAnalysis from "@/components/results/DeepAnalysis";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";

describe("DeepAnalysis", () => {
  it("renders a fallback severity label when a grid item has missing severity", () => {
    const grid = [
      {
        layer: "Neural Vision",
        finding: "Sparse mention coverage for core brand entities.",
        neural_correlation: "Low entity consistency in generative responses.",
        llm_behavior_projection: "Models may infer competitor entities first.",
        architect_fix: "Increase entity anchoring in high-authority content blocks.",
        priority_weight: 1,
      },
    ] as unknown as NonNullable<CanonicalAuditReport["debate_findings"]>;

    expect(() => render(<DeepAnalysis grid={grid} />)).not.toThrow();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });
});
