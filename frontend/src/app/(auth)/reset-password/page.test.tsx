import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/auth/AuthShell", () => ({
  default: ({
    chipLabel,
    title,
    accentText,
    subtitle,
    footerText,
    footerCtaLabel,
    footerCtaHref,
    children,
  }: {
    chipLabel: string;
    title: string;
    accentText?: string;
    subtitle: string;
    footerText: string;
    footerCtaLabel: string;
    footerCtaHref: string;
    children: React.ReactNode;
  }) => (
    <div>
      <div>{chipLabel}</div>
      <div>{title}</div>
      <div>{accentText}</div>
      <div>{subtitle}</div>
      <div>{footerText}</div>
      <a href={footerCtaHref}>{footerCtaLabel}</a>
      {children}
    </div>
  ),
}));

vi.mock("@/components/auth/ResetPasswordForm", () => ({
  ResetPasswordForm: ({ mode }: { mode: "invite" | "reset" }) => <div>Form mode: {mode}</div>,
}));

vi.mock("@/lib/auth-branding", () => ({
  fetchAuthBranding: vi.fn(async () => null),
}));

describe("ResetPasswordPage", () => {
  it("renders onboarding copy for client invitation links", async () => {
    const { default: ResetPasswordPage } = await import("@/app/(auth)/reset-password/page");
    render(await ResetPasswordPage({ searchParams: { flow: "invite" } }));

    expect(screen.getByText("Portal Onboarding")).toBeInTheDocument();
    expect(screen.getByText("Set your password")).toBeInTheDocument();
    expect(
      screen.getByText("Choose a strong password to activate your client portal access.")
    ).toBeInTheDocument();
    expect(screen.getByText("Already set up?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.getByText("Form mode: invite")).toBeInTheDocument();
  });

  it("keeps reset-password copy for normal recovery links", async () => {
    const { default: ResetPasswordPage } = await import("@/app/(auth)/reset-password/page");
    render(await ResetPasswordPage({ searchParams: {} }));

    expect(screen.getByText("Session Recovery")).toBeInTheDocument();
    expect(screen.getByText("Set a new password")).toBeInTheDocument();
    expect(
      screen.getByText("Choose a strong password to secure your account.")
    ).toBeInTheDocument();
    expect(screen.getByText("Need another link?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new link" })).toHaveAttribute(
      "href",
      "/forgot-password"
    );
    expect(screen.getByText("Form mode: reset")).toBeInTheDocument();
  });
});
