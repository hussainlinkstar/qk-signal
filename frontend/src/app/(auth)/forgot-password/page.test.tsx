import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ForgotPasswordPage from "@/app/(auth)/forgot-password/page";

const forgotPasswordMock = vi.fn();

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/lib/auth-branding", () => ({
  fetchAuthBranding: vi.fn(async () => null),
}));

vi.mock("@/services/auth.service", () => ({
  default: {
    forgotPassword: (...args: unknown[]) => forgotPasswordMock(...args),
  },
}));

/**
 * SIGV2-1088: the recovery screen used to offer its own route back to sign-in
 * inside the card body while AuthShell was already rendering one in the shared
 * footer, so the confirmation state stacked two links to /login. The shared
 * footer is the single owner of that secondary link on every auth screen.
 */
const signInLinks = () =>
  screen.getAllByRole("link").filter((link) => link.getAttribute("href") === "/login");

describe("ForgotPasswordPage sign-in link", () => {
  beforeEach(() => {
    forgotPasswordMock.mockReset();
  });

  it("renders exactly one sign-in link on the recovery form", async () => {
    render(await ForgotPasswordPage());

    expect(screen.getByText("Already recovered access?")).toBeInTheDocument();
    expect(signInLinks()).toHaveLength(1);
    expect(signInLinks()[0]).toHaveAccessibleName("Sign in");
  });

  it("still renders exactly one sign-in link after the email is submitted", async () => {
    forgotPasswordMock.mockResolvedValue(undefined);

    render(await ForgotPasswordPage());

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "user@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send reset instructions" }));

    expect(await screen.findByRole("heading", { name: "Check your inbox" })).toBeInTheDocument();
    await waitFor(() => {
      expect(forgotPasswordMock).toHaveBeenCalledWith("user@example.com");
    });

    expect(screen.getByRole("link", { name: "Request new link" })).toBeInTheDocument();
    expect(signInLinks()).toHaveLength(1);
    expect(signInLinks()[0]).toHaveAccessibleName("Sign in");
  });
});
