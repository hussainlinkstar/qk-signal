import { describe, expect, it } from "vitest";

import {
  resolveAlphaColor,
  resolveDashboardDocumentTitle,
  resolveWorkspaceBrandName,
  resolveWorkspaceBrandingStyle,
  type WorkspaceBrandingPayload,
} from "@/lib/workspaceBranding";

const sampleBranding: WorkspaceBrandingPayload = {
  workspace_name: "Agency Workspace",
  company_name: "Acme Signals",
  custom_page_title: "Acme Command Center",
  custom_logo_url: null,
  custom_favicon_url: null,
  primary_color: "#FF4D2D",
  secondary_color: "#14B8A6",
  hide_powered_by: true,
};

describe("workspaceBranding helpers", () => {
  it("prefers the company name when resolving the workspace brand label", () => {
    expect(resolveWorkspaceBrandName(sampleBranding)).toBe("Acme Signals");
    expect(
      resolveWorkspaceBrandName({
        ...sampleBranding,
        company_name: "",
      })
    ).toBe("Agency Workspace");
  });

  it("builds branded dashboard token overrides from workspace colors", () => {
    const style = resolveWorkspaceBrandingStyle(sampleBranding) as Record<string, string>;

    expect(style["--primary"]).toBe("#FF4D2D");
    expect(style["--accent"]).toBe("#14B8A6");
    expect(style["--chart-1"]).toBe("#FF4D2D");
    expect(style["--chart-2"]).toBe("#14B8A6");
    expect(style["--shadow-primary"]).toContain("#FF4D2D24");
  });

  it("derives route-aware dashboard titles from the workspace page title", () => {
    expect(resolveDashboardDocumentTitle("/dashboard", sampleBranding)).toBe(
      "Workspace Overview | Acme Command Center"
    );
    expect(resolveDashboardDocumentTitle("/dashboard/account-settings", sampleBranding)).toBe(
      "My Profile | Acme Command Center"
    );
    expect(resolveDashboardDocumentTitle("/dashboard/audit/42", sampleBranding)).toBe(
      "Assessment Report | Acme Command Center"
    );
    expect(
      resolveDashboardDocumentTitle("/dashboard/projects/7/seo", sampleBranding, "Client Project")
    ).toBe("Client Project | SEO | Acme Command Center");
  });

  it("resolveAlphaColor successfully adds alpha hex", () => {
    expect(resolveAlphaColor("#FF4D2D", 0.14)).toBe("rgba(255, 77, 45, 0.14)");
    expect(resolveAlphaColor("var(--primary)", 0.22)).toBe(
      "color-mix(in srgb, var(--primary) 22%, transparent)"
    );
  });
});
