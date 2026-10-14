import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/auth/LoginForm";
import { AUTH_REDIRECT_PARAM } from "@/constants/auth";

const { routerPush, searchParamsState, loginMock, loginWithPasskeyMock, checkHasPasskeysMock } =
  vi.hoisted(() => ({
    routerPush: vi.fn(),
    searchParamsState: new URLSearchParams(),
    loginMock: vi.fn(),
    loginWithPasskeyMock: vi.fn(),
    checkHasPasskeysMock: vi.fn().mockResolvedValue(false),
  }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => searchParamsState,
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ login: loginMock, setSession: vi.fn() }),
}));

vi.mock("@/services/passkey.service", () => ({
  loginWithPasskey: loginWithPasskeyMock,
  checkHasPasskeys: checkHasPasskeysMock,
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/auth/AuthFormSections", () => ({
  AuthFooterHelper: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AuthForgotPasswordLink: ({ href, label }: { href: string; label: string }) => (
    <a href={href}>{label}</a>
  ),
  AuthFormDivider: ({ label }: { label: string }) => <div>{label}</div>,
  AuthFormSocialSection: () => <div>Social</div>,
  AuthSubmitButton: ({ children }: { children: React.ReactNode }) => (
    <button type="submit">{children}</button>
  ),
}));

vi.mock("@/components/ui/TextField", () => {
  const MockTextField = React.forwardRef<
    HTMLInputElement,
    {
      label: string;
      type?: string;
      error?: string;
      variant?: string;
    } & React.InputHTMLAttributes<HTMLInputElement>
  >(({ label, type = "text", error: _error, variant: _variant, ...props }, ref) => (
    <label>
      {label}
      <input ref={ref} aria-label={label} type={type} {...props} />
    </label>
  ));

  MockTextField.displayName = "MockTextField";

  return {
    default: MockTextField,
  };
});

describe("LoginForm", () => {
  beforeEach(() => {
    routerPush.mockReset();
    loginMock.mockReset();
    loginMock.mockResolvedValue(undefined);
    searchParamsState.forEach((_, key) => searchParamsState.delete(key));
  });

  it("navigates to redirect_url after successful login", async () => {
    searchParamsState.set(AUTH_REDIRECT_PARAM, "/dashboard/account-settings");

    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(routerPush).toHaveBeenCalledWith("/dashboard/account-settings");
    });

    expect(loginMock).toHaveBeenCalledWith(
      expect.objectContaining({
        email: "test@example.com",
        password: "secret123",
        remember_me: true,
      })
    );
  });

  it("submits remember_me false when checkbox is unchecked", async () => {
    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret123" } });
    fireEvent.click(screen.getByLabelText("Remember me"));
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith(
        expect.objectContaining({
          remember_me: false,
        })
      );
    });
  });

  it("redirects to dashboard by default after successful login", async () => {
    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(routerPush).toHaveBeenCalledWith("/dashboard");
    });
  });
  // SIGV2-1307 ---------------------------------------------------------------
  // QA logged a blocker: no verification email arrived, and Resend showed no
  // confirmation. The mail had in fact been sent, five messages to that
  // address, each accepted by SMTP on the first attempt. What was missing was
  // any trace of it on screen.
  //
  // Registration fired a toast and immediately pushed to /login, so the one
  // sentence telling a new user what happens next raced a route change. And
  // Resend reported only as a toast, which is the wrong shape for the single
  // thing a blocked user is waiting on.
  describe("telling a new account what happened", () => {
    it("says an email is on its way, and to which address", () => {
      searchParamsState.set("registered", "jane@example.com");

      render(<LoginForm />);

      const notice = screen.getByRole("status");
      expect(notice.textContent).toContain("Check your inbox");
      // Naming the address matters: "check your inbox" is useless if the
      // inbox is not the one the reader is looking at.
      expect(notice.textContent).toContain("jane@example.com");
    });

    it("shows the sign-in form normally when nobody just registered", () => {
      render(<LoginForm />);

      expect(screen.queryByText("Check your inbox")).not.toBeInTheDocument();
    });
  });
});
