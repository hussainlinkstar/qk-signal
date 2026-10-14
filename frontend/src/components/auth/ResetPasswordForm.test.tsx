import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";

const routerPush = vi.fn();
const searchParamsState = new URLSearchParams("token=invite-token");
const resetPasswordMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => searchParamsState,
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

vi.mock("@/services/auth.service", () => ({
  default: {
    resetPassword: (...args: unknown[]) => resetPasswordMock(...args),
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
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    loading?: boolean;
    loadingText?: React.ReactNode;
  }) => <button {...props}>{loading ? (loadingText ?? children) : children}</button>,
}));

describe("ResetPasswordForm", () => {
  beforeEach(() => {
    routerPush.mockReset();
    resetPasswordMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    searchParamsState.set("token", "invite-token");
  });

  it("uses invite wording and blocks passwords that backend would reject", async () => {
    render(<ResetPasswordForm mode="invite" />);

    expect(screen.getByRole("button", { name: "Set up password" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "Password1" },
    });
    fireEvent.change(screen.getByLabelText("Confirm Password"), {
      target: { value: "Password1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set up password" }));

    expect(await screen.findByText("Must contain a special character")).toBeInTheDocument();
    expect(resetPasswordMock).not.toHaveBeenCalled();
  });

  it("submits a valid invited-user password and redirects to login", async () => {
    resetPasswordMock.mockResolvedValue(undefined);

    render(<ResetPasswordForm mode="invite" />);

    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "Password1!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm Password"), {
      target: { value: "Password1!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set up password" }));

    await waitFor(() => {
      expect(resetPasswordMock).toHaveBeenCalledWith("invite-token", "Password1!");
    });

    expect(toastSuccess).toHaveBeenCalledWith("Password set successfully.");
    expect(routerPush).toHaveBeenCalledWith("/login");
  });
});
