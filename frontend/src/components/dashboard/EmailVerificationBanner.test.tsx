import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EmailVerificationBanner from "@/components/dashboard/EmailVerificationBanner";

const resendVerificationEmailMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/services/auth.service", () => ({
  default: {
    resendVerificationEmail: (...args: unknown[]) => resendVerificationEmailMock(...args),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

describe("EmailVerificationBanner", () => {
  it("resends verification email", async () => {
    resendVerificationEmailMock.mockResolvedValue(undefined);

    render(<EmailVerificationBanner email="user@example.com" onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Resend verification email" }));

    await waitFor(() => {
      expect(resendVerificationEmailMock).toHaveBeenCalledWith("user@example.com");
    });
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("calls dismiss callback", () => {
    const onDismiss = vi.fn();

    render(<EmailVerificationBanner email="user@example.com" onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
