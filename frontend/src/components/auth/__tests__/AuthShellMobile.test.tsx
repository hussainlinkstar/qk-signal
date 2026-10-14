import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuthShell from "@/components/auth/AuthShell";

vi.mock("@/components/signal/SignalBrandLockup", () => ({
  default: () => <div>App logo</div>,
}));

describe("AuthShell mobile layout", () => {
  it("renders auth shell content at 375px viewport width", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 375 });
    window.dispatchEvent(new Event("resize"));

    render(
      <AuthShell
        chipLabel="Secure Access"
        title="Welcome back"
        subtitle="Sign in securely and continue."
        footerText="Need an account?"
        footerCtaLabel="Create Account"
        footerCtaHref="/register"
      >
        <div>Auth body</div>
      </AuthShell>
    );

    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByText("Auth body")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create Account" })).toBeInTheDocument();
  });
});
