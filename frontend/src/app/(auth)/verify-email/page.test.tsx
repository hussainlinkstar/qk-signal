import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import VerifyEmailPage from "@/app/(auth)/verify-email/page";

const verifyEmailMock = vi.fn();
const resendVerificationEmailMock = vi.fn();

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams("token=expired-token"),
}));

vi.mock("@/lib/auth-branding", () => ({
  fetchAuthBranding: vi.fn(async () => null),
}));

vi.mock("@/services/auth.service", () => ({
  default: {
    verifyEmail: (...args: unknown[]) => verifyEmailMock(...args),
    resendVerificationEmail: (...args: unknown[]) => resendVerificationEmailMock(...args),
  },
}));

/**
 * SIGV2-1088: the verification failure card offered its own "Sign in" button
 * while AuthShell was already rendering one in the shared footer, so the error
 * state stacked two links to /login with the identical accessible name.
 */
const signInLinks = () =>
  screen.getAllByRole("link").filter((link) => link.getAttribute("href") === "/login");

describe("VerifyEmailPage sign-in link", () => {
  beforeEach(() => {
    verifyEmailMock.mockReset();
    resendVerificationEmailMock.mockReset();
  });

  it("renders exactly one sign-in link when verification fails", async () => {
    verifyEmailMock.mockRejectedValue(new Error("Verification token expired."));

    render(await VerifyEmailPage());

    expect(await screen.findByRole("heading", { name: "Verification failed" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resend verification email" })).toBeInTheDocument();
    expect(signInLinks()).toHaveLength(1);
    expect(signInLinks()[0]).toHaveAccessibleName("Sign in");
  });

  it("renders exactly one sign-in link when verification succeeds", async () => {
    verifyEmailMock.mockResolvedValue(undefined);

    render(await VerifyEmailPage());

    expect(await screen.findByRole("heading", { name: "Email verified" })).toBeInTheDocument();
    expect(signInLinks()).toHaveLength(1);
    expect(signInLinks()[0]).toHaveAccessibleName("Sign in");
  });
});
