import { readFileSync } from "node:fs";
import path from "node:path";

import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AuthShell from "@/components/auth/AuthShell";

const renderShell = (branding?: Parameters<typeof AuthShell>[0]["branding"]) =>
  render(
    <AuthShell
      chipLabel="Secure Access"
      title="Welcome back"
      subtitle="Sign in securely and continue."
      footerText="Need an account?"
      footerCtaLabel="Create Account"
      footerCtaHref="/register"
      branding={branding}
    >
      <div>Auth body</div>
    </AuthShell>
  );

const signalLogoAlt = "Qiko";

describe("AuthShell logo", () => {
  it("renders the MVP Qiko logo with a separate Signal wordmark", () => {
    renderShell();

    const logo = screen.getByAltText(signalLogoAlt);
    expect(logo.getAttribute("src")).toContain("qiko-logo.png");
    expect(logo).toHaveAttribute("height", "32");
    expect(screen.getByText("Signal")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Qiko home" })).toContainElement(logo);
  });

  it("uses a dedicated light auth surface without an animated entrance", () => {
    renderShell();

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("data-signal-auth");
    expect(main).toHaveAttribute("id", "main-content");
    expect(main.querySelector('[style*="opacity: 0"]')).toBeNull();
  });

  it("still renders the tenant's own logo when customLogoUrl is set, never the Signal fallback", () => {
    renderShell({ customLogoUrl: "https://cdn.example.com/tenant-logo.png", companyName: "Acme" });

    const tenantLogo = screen.getByAltText("Acme");
    expect(tenantLogo).toBeInTheDocument();
    expect(tenantLogo.getAttribute("src")).toBe("https://cdn.example.com/tenant-logo.png");
    expect(screen.queryByAltText(signalLogoAlt)).not.toBeInTheDocument();
  });
});

describe("dashboard branding is unaffected by the auth lockup", () => {
  const touchedFiles = [
    "src/components/signal/SignalAppShell.tsx",
    "src/components/signal/SignalAppFooter.tsx",
  ];

  it.each(touchedFiles)("%s does not reference /qiko-logo.png", (file) => {
    const source = readFileSync(path.resolve(process.cwd(), file), "utf8");
    expect(source).not.toContain("/qiko-logo.png");
  });
});
