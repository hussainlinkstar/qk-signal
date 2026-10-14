import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/auth/LoginForm";

const routerPush = vi.fn();
const loginMock = vi.fn();
const setSessionMock = vi.fn();
const searchParamsState = new URLSearchParams();
const toastError = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => searchParamsState,
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    login: loginMock,
    setSession: setSessionMock,
  }),
}));

vi.mock("@/services/passkey.service", () => ({
  loginWithPasskey: vi.fn(),
  checkHasPasskeys: vi.fn().mockResolvedValue(false),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

vi.mock("@/components/auth/AuthFormSections", () => ({
  AuthForgotPasswordLink: ({ href, label }: { href: string; label: string }) => (
    <a href={href}>{label}</a>
  ),
  AuthFormDivider: ({ label }: { label: string }) => <div>{label}</div>,
  AuthFormSocialSection: () => <div>Social</div>,
  AuthSubmitButton: ({
    children,
    loading,
    loadingText,
  }: {
    children: React.ReactNode;
    loading: boolean;
    loadingText: string;
  }) => <button type="submit">{loading ? loadingText : children}</button>,
}));

vi.mock("@/components/ui/TextField", () => {
  const MockTextField = React.forwardRef<
    HTMLInputElement,
    {
      label: string;
      error?: string;
      variant?: string;
    } & React.InputHTMLAttributes<HTMLInputElement>
  >(({ label, error: _error, variant: _variant, ...props }, ref) => (
    <label>
      {label}
      <input ref={ref} aria-label={label} {...props} />
    </label>
  ));

  MockTextField.displayName = "MockTextField";

  return {
    default: MockTextField,
  };
});

describe("LoginForm state handling", () => {
  beforeEach(() => {
    routerPush.mockReset();
    loginMock.mockReset();
    setSessionMock.mockReset();
    toastError.mockReset();
    searchParamsState.forEach((_, key) => searchParamsState.delete(key));
    sessionStorage.clear();
  });

  it("shows session-expired copy and sign-in CTA", () => {
    searchParamsState.set("session_expired", "true");

    render(<LoginForm />);

    expect(screen.getByText("Your session expired. Sign in to continue.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows submit loading state while request is in-flight", async () => {
    loginMock.mockImplementation(() => new Promise(() => {}));

    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Secret123!" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Completing sign-in...")).toBeInTheDocument();
  });

  it("recovers from submit failure and keeps the sign-in CTA active", async () => {
    loginMock.mockRejectedValue(new Error("Invalid credentials"));

    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrongpass" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(toastError).toHaveBeenCalledWith("Invalid credentials");
    });

    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});
