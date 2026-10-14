import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AuditEvidenceStrip from "./AuditEvidenceStrip";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

describe("Audit evidence warnings", () => {
  it("keeps degraded audit evidence visible in the shared warning alert", () => {
    render(
      <AuditEvidenceStrip
        title="SEO evidence"
        diagnostics={{
          module: "seo",
          status: "partial",
          summary: "Some evidence is unavailable.",
          fields: [],
          issues: ["Search data could not be loaded.", "A fallback measurement was used."],
        }}
      />
    );
    const warning = screen.getByRole("alert");
    expect(warning).toHaveAttribute("data-signal-alert", "warning");
    expect(warning).toHaveTextContent("Search data could not be loaded.");
    expect(warning).toHaveTextContent("A fallback measurement was used.");
    expect(warning.querySelectorAll("li")).toHaveLength(2);
    expect(warning.querySelector("svg")).not.toBeNull();
  });

  it("does not announce a warning for measured evidence without issues", () => {
    render(
      <AuditEvidenceStrip
        title="SEO evidence"
        diagnostics={{
          module: "seo",
          status: "measured",
          summary: "Evidence is available.",
          fields: [],
          issues: [],
        }}
      />
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
