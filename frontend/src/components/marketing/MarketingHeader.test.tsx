import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MarketingHeader from "@/components/marketing/MarketingHeader";

const authState = {
  user: null as { name?: string | null; email?: string | null } | null,
  logout: vi.fn(async () => undefined),
};

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { resolvedLanguage: "en", language: "en" },
    t: (key: string, options?: { defaultValue?: string }) => {
      const values: Record<string, string> = {
        "nav.analysis": "Features",
        "nav.product": "Product",
        "nav.resources": "Resources",
        "nav.guestAudit": "Free Assessment",
        "nav.sampleReport": "Sample Report",
        "nav.qiko": "Home",
        "nav.labs": "Labs",
        "nav.login": "Login",
        "nav.createAccount": "Create account",
        "nav.startFreeAssessment": "Start Free Assessment",
        "nav.openMenu": "Open navigation menu",
      };

      return values[key] ?? options?.defaultValue ?? key;
    },
  }),
  // The i18n bootstrap calls `i18n.use(initReactI18next)`, so the mock has to
  // provide it. Without it the whole module failed to load and the file
  // reported "no tests" rather than a failing assertion.
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@/components/auth/custom-auth", () => ({
  SignedIn: ({ children }: { children: React.ReactNode }) =>
    authState.user ? <>{children}</> : null,
  SignedOut: ({ children }: { children: React.ReactNode }) =>
    authState.user ? null : <>{children}</>,
  UserButton: () => <div>User button</div>,
  useAuth: () => authState,
}));

vi.mock("@/components/signal/SignalBrandLockup", () => ({
  default: () => <div>Brand lockup</div>,
}));

vi.mock("@/components/navigation/MobileHeaderMenu", () => ({
  default: () => null,
}));

describe("MarketingHeader", () => {
  beforeEach(() => {
    authState.user = null;
    authState.logout.mockClear();
  });

  it("shows only live navigation links for signed-out visitors", () => {
    render(<MarketingHeader />);

    expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Labs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Login" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create account" })).toBeInTheDocument();
    // Retired along with the duplicate marketing pages (WEB-1008): no dead links left.
    expect(screen.queryByRole("link", { name: "Features" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Free Assessment" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sample Report" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Search Volatility" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Pricing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Documentation" })).not.toBeInTheDocument();
  });
});
