import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";

const forgotPasswordMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

vi.mock("@/services/auth.service", () => ({
  default: {
    forgotPassword: (...args: unknown[]) => forgotPasswordMock(...args),
  },
}));

vi.mock("@/components/ui/TextField", () => {
  const MockTextField = React.forwardRef<
    HTMLInputElement,
    {
      label: string;
      error?: string;
      variant?: string;
    } & React.InputHTMLAttributes<HTMLInputElement>
  >(({ label, error, variant: _variant, ...props }, ref) => (
    <label>
      {label}
      <input ref={ref} aria-label={label} {...props} />
      {error ? <span>{error}</span> : null}
    </label>
  ));

  MockTextField.displayName = "MockTextField";

  return {
    default: MockTextField,
  };
});

vi.mock("@/components/ui/Button", () => ({
  default: ({
    children,
    loading,
    loadingText,
    className,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    loading?: boolean;
    loadingText?: React.ReactNode;
    className?: string;
  }) => (
    <button className={className} {...props}>
      {loading ? (loadingText ?? children) : children}
    </button>
  ),
  buttonClasses: ({ className }: { className?: string } = {}) => className ?? "button-mock",
}));

describe("ForgotPasswordForm", () => {
  beforeEach(() => {
    forgotPasswordMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("renders the recovery form with the current auth state header", () => {
    render(<ForgotPasswordForm />);

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send reset instructions" })).toBeInTheDocument();
  });

  it("submits the email and shows the inbox confirmation state", async () => {
    forgotPasswordMock.mockResolvedValue(undefined);

    render(<ForgotPasswordForm />);

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "user@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send reset instructions" }));

    await waitFor(() => {
      expect(forgotPasswordMock).toHaveBeenCalledWith("user@example.com");
    });

    expect(toastSuccess).toHaveBeenCalledWith(
      "If an account exists, reset instructions are on the way."
    );
    expect(await screen.findByRole("heading", { name: "Check your inbox" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request new link" })).toBeInTheDocument();
  });
});
