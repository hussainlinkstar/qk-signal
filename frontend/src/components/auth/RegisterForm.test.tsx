import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterForm } from "@/components/auth/RegisterForm";

// RegisterForm reads NEXT_PUBLIC_ENABLE_SSO into a module-level const, so the
// flag has to be set before the module is imported. vi.hoisted runs first.
// Without it the social section never renders and this test cannot pass.
// Note the flag is set nowhere in the repo, so social login is dark in
// production as well; this covers the code path for when it is switched on.
vi.hoisted(() => {
  process.env.NEXT_PUBLIC_ENABLE_SSO = "true";
});

// Test files share a worker process, so process.env persists across them.
// Without this, LoginForm and anything else reading the flag would silently see
// SSO enabled depending on file order.
afterAll(() => {
  delete process.env.NEXT_PUBLIC_ENABLE_SSO;
});

const { authFormSocialSectionMock, registerMock, routerPush, toastSuccess, toastError } =
  vi.hoisted(() => ({
    authFormSocialSectionMock: vi.fn((_props?: Record<string, unknown>) => <div>Social</div>),
    registerMock: vi.fn(),
    routerPush: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
  }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

vi.mock("@/services/auth.service", () => ({
  default: {
    register: (...args: unknown[]) => registerMock(...args),
  },
}));

vi.mock("@/components/auth/AuthFormSections", () => ({
  AuthFormDivider: ({ label }: { label: string }) => <div>{label}</div>,
  AuthFormSocialSection: (props: Record<string, unknown>) => authFormSocialSectionMock(props),
  AuthSubmitButton: ({ children }: { children: React.ReactNode }) => (
    <button type="submit">{children}</button>
  ),
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

describe("RegisterForm", () => {
  beforeEach(() => {
    authFormSocialSectionMock.mockClear();
    registerMock.mockReset();
    routerPush.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("uses the compact icon-row social layout", () => {
    render(<RegisterForm />);

    expect(authFormSocialSectionMock).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "register",
        variant: "icon-row",
      })
    );
  });

  it("submits a valid registration payload and redirects to login", async () => {
    registerMock.mockResolvedValue(undefined);

    render(<RegisterForm />);

    // SIGV2-1307: the label was "Name" beside a placeholder reading "Agency
    // or company name". The placeholder was the honest half: this field
    // writes `User.company_name` through `normalize_company_name`, and a
    // person's own name is not stored here at all.
    fireEvent.change(screen.getByLabelText("Company or agency name"), {
      target: { value: "Jane Doe" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "jane@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "Password1!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm Password"), {
      target: { value: "Password1!" },
    });
    fireEvent.click(screen.getByLabelText("I agree to the Terms of Service and Privacy Policy"));
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(registerMock).toHaveBeenCalledWith({
        name: "Jane Doe",
        email: "jane@example.com",
        password: "Password1!",
      });
    });

    expect(toastSuccess).toHaveBeenCalledWith(
      "Account created. Check your inbox to verify your email."
    );

    // SIGV2-1307: the address travels, so /login can say what happened in
    // place. The toast alone was racing this navigation, which is why QA
    // logged "Create account sends the user to /login with no check your
    // email step" while the mail had in fact been sent.
    expect(routerPush).toHaveBeenCalledWith("/login?registered=jane%40example.com");
  });

  it("blocks registration until legal consent is checked", async () => {
    render(<RegisterForm />);

    fireEvent.change(screen.getByLabelText("Company or agency name"), {
      target: { value: "Jane Doe" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "jane@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "Password1!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm Password"), {
      target: { value: "Password1!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByText("You must agree to the Terms of Service and Privacy Policy.")
    ).toBeInTheDocument();
    expect(registerMock).not.toHaveBeenCalled();
  });
});
