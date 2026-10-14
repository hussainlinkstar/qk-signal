import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AccountSettingsPage from "@/app/(app)/dashboard/account-settings/page";

const authState = {
  getToken: vi.fn(async () => "token-123"),
  isLoading: false,
  isSignedIn: true,
  logout: vi.fn(async () => undefined),
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
  useUser: () => ({
    user: {
      id: "1",
      primaryEmailAddress: { emailAddress: "user@example.com" },
      fullName: "Jane Doe",
    },
  }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => authState,
}));

vi.mock("@/services/passkey.service", () => ({
  registerPasskey: vi.fn(),
  listPasskeys: vi.fn(async () => [
    {
      id: 7,
      name: "MacBook Touch ID",
      created_at: "2026-07-30T12:00:00Z",
      last_used_at: null,
      backed_up: false,
    },
  ]),
  renamePasskey: vi.fn(),
  deletePasskey: vi.fn(),
}));

let mfaEnabled = false;

describe("AccountSettingsPage", () => {
  beforeEach(() => {
    mfaEnabled = false;
    authState.getToken.mockClear();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }

      const payloadByPath: Record<string, unknown> = {
        "/api/users/me": {
          id: "1",
          email: "user@example.com",
          role: "user",
          subscription: { plan_type: "plan_specialist", status: "active" },
        },
        "/api/users/me/profile": {
          email: "user@example.com",
          role: "user",
          name: "Jane Doe",
        },
        "/api/users/me/notification-preferences": {
          notifications_enabled: true,
        },
        "/api/users/me/branding": {
          custom_logo_url: "",
          primary_color: "#FF4D2D",
          secondary_color: "#14B8A6",
        },
        "/api/users/me/mfa/status": {
          enabled: mfaEnabled,
        },
        "/api/users/me/mfa/setup": {
          qr_code_url: "data:image/png;base64,cXI=",
          secret: "TESTSECRET",
          account_name: "user@example.com",
          setup_token: "setup-token",
        },
        "/api/billing/invoices?limit=5": {
          invoices: [],
        },
        "/api/auth/linked-identities": {
          identities: [{ provider: "microsoft", configured: true, linked: false, linked_at: null }],
        },
      };

      if (!(input in payloadByPath)) {
        throw new Error(`Unexpected fetch call: ${input}`);
      }

      return new Response(JSON.stringify(payloadByPath[input]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows invoice service unavailability without replacing it with an empty history", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    const baseline = fetchMock.getMockImplementation();
    let invoiceCalls = 0;
    fetchMock.mockImplementation(async (input, init) => {
      if (input === "/api/billing/invoices?limit=5") {
        invoiceCalls += 1;
        return new Response(
          JSON.stringify({
            detail: {
              code: "invoice_history_unavailable",
              message: "Invoice history is temporarily unavailable.",
            },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } }
        );
      }
      return baseline!(input, init);
    });

    render(<AccountSettingsPage />);

    expect(
      await screen.findByText(
        "Invoice history is temporarily unavailable. Your billing data has not been changed."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/No invoices yet/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(invoiceCalls).toBe(2));
    expect(fetchMock.mock.calls.filter(([input]) => input === "/api/users/me")).toHaveLength(1);
  });

  it("uses the canonical My Profile title", async () => {
    render(<AccountSettingsPage />);

    expect(await screen.findByRole("heading", { name: "My Profile" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Account Settings" })).not.toBeInTheDocument();
  });

  it("uses the shared accessible tabs contract for account sections", async () => {
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");

    const tablist = screen.getByRole("tablist");
    const profileTab = within(tablist).getByRole("tab", { name: "Profile" });
    const profilePanel = screen.getByRole("tabpanel", { name: "Profile" });

    expect(profileTab).toHaveAttribute("aria-selected", "true");
    expect(profileTab).toHaveAttribute("aria-controls", profilePanel.id);
    expect(profilePanel).toHaveAttribute("aria-labelledby", profileTab.id);

    fireEvent.click(within(tablist).getByRole("tab", { name: "Branding" }));
    const brandingTab = within(tablist).getByRole("tab", { name: "Branding" });
    const brandingPanel = screen.getByRole("tabpanel", { name: "Branding" });

    expect(brandingTab).toHaveAttribute("aria-selected", "true");
    expect(brandingTab).toHaveAttribute("aria-controls", brandingPanel.id);
    expect(brandingPanel).toHaveAttribute("aria-labelledby", brandingTab.id);
  });

  it("requires programmatic labels for ProfileSection fields", async () => {
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");

    [
      "Display name",
      "Email",
      "Role",
      "Legal company name",
      "Registration number",
      "VAT / tax number",
      "Stripe customer ID",
      "Billing email",
      "Phone",
      "Website",
      "Address line 1",
      "Address line 2",
      "City",
      "State / county",
      "Postal code",
      "Country (ISO2)",
    ].forEach((name) => expect(screen.getByLabelText(name, { exact: true })).toBeInTheDocument());
  });

  it("exposes the Tax exempt control as a named switch", async () => {
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");

    expect(screen.getByRole("switch", { name: "Tax exempt" })).toHaveAttribute(
      "aria-checked",
      "false"
    );
  });

  it("requires programmatic labels for the SecuritySection password fields", async () => {
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");
    fireEvent.click(screen.getByRole("tab", { name: "Security" }));

    await screen.findByRole("heading", { name: "Change Password" });
    ["Current password", "New password", "Confirm new password"].forEach((name) =>
      expect(screen.getByLabelText(name, { exact: true })).toBeInTheDocument()
    );
  });

  it("requires programmatic labels for SecuritySection MFA fields", async () => {
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");
    fireEvent.click(screen.getByRole("tab", { name: "Security" }));

    fireEvent.click(await screen.findByRole("button", { name: "Set up authenticator" }));
    expect(await screen.findByLabelText("Manual setup key", { exact: true })).toHaveAttribute(
      "readonly"
    );
    expect(screen.getByLabelText("Authenticator code", { exact: true })).toBeInTheDocument();
  });

  it("requires a programmatic label for the SecuritySection MFA disable field", async () => {
    mfaEnabled = true;
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");
    fireEvent.click(screen.getByRole("tab", { name: "Security" }));

    expect(
      await screen.findByLabelText("Authenticator code to disable", { exact: true })
    ).toBeInTheDocument();
  });

  it("requires a programmatic label for the SecuritySection passkey field", async () => {
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");
    fireEvent.click(screen.getByRole("tab", { name: "Security" }));

    fireEvent.click(await screen.findByRole("button", { name: "Add Passkey" }));
    expect(screen.getByLabelText("Passkey name", { exact: true })).toBeInTheDocument();
  });

  it("requires a programmatic label for the SecuritySection passkey rename field", async () => {
    render(<AccountSettingsPage />);
    await screen.findByText("Identity");
    fireEvent.click(screen.getByRole("tab", { name: "Security" }));

    fireEvent.click(await screen.findByRole("button", { name: "Rename" }));
    expect(screen.getByLabelText("Passkey name", { exact: true })).toHaveValue("MacBook Touch ID");
  });

  it("renders normalized navigation labels for account settings sections", async () => {
    render(<AccountSettingsPage />);

    await screen.findByText("Identity");

    expect(screen.getByRole("heading", { name: /my profile/i })).toBeInTheDocument();
    expect(screen.queryByText("White-Label")).not.toBeInTheDocument();
    expect(screen.queryByText("Advanced")).not.toBeInTheDocument();
    expect(screen.queryByText("REL_2026.4")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Branding" }));

    expect(await screen.findByText("Report Branding", { selector: "h3" })).toBeInTheDocument();
  });
});
