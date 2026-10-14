import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SecuritySection from "@/app/(app)/dashboard/account-settings/components/SecuritySection";
import { useAccountSettings } from "@/app/(app)/dashboard/account-settings/useAccountSettings";

/**
 * SIGV2-1257.
 *
 * SIGV2-1239 stopped a Microsoft sign-in from auto-linking to an existing
 * account on an unverified email claim, which left no way to use Microsoft
 * at all. The recovery path is here, and these tests hold its shape: the
 * account's own password plus an explicit confirmation before anything is
 * sent, and no affordance at all where the provider is not configured.
 */

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
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => authState,
}));

vi.mock("@/services/passkey.service", () => ({
  registerPasskey: vi.fn(),
  listPasskeys: vi.fn(async () => []),
  renamePasskey: vi.fn(),
  deletePasskey: vi.fn(),
}));

const BOOT_PAYLOADS: Record<string, unknown> = {
  "/api/users/me": {
    id: "1",
    email: "user@example.com",
    role: "user",
    subscription: { plan_type: "plan_specialist", status: "active" },
  },
  "/api/users/me/profile": { email: "user@example.com", role: "user", name: "Jane Doe" },
  "/api/users/me/notification-preferences": { notifications_enabled: true },
  "/api/users/me/branding": { custom_logo_url: "", primary_color: "", secondary_color: "" },
  "/api/users/me/mfa/status": { enabled: false },
  "/api/billing/invoices?limit=5": { invoices: [] },
};

type LinkState = {
  configured: boolean;
  linked: boolean;
  startStatus: number;
  startBody: unknown;
};

let linkState: LinkState;
let startRequests: RequestInit[] = [];
let navigatedTo: string[] = [];

const installFetchMock = () => {
  startRequests = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    if (url === "/api/auth/linked-identities") {
      return new Response(
        JSON.stringify({
          identities: [
            {
              provider: "microsoft",
              configured: linkState.configured,
              linked: linkState.linked,
              linked_at: null,
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (url === "/api/auth/linked-identities/microsoft/start" && method === "POST") {
      startRequests.push(init ?? {});
      return new Response(JSON.stringify(linkState.startBody), {
        status: linkState.startStatus,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (!(url in BOOT_PAYLOADS)) {
      throw new Error(`Unexpected fetch call: ${method} ${url}`);
    }

    return new Response(JSON.stringify(BOOT_PAYLOADS[url]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
};

const SecurityHarness: React.FC = () => {
  const settings = useAccountSettings();
  return <SecuritySection settings={settings} />;
};

const renderSection = async () => {
  render(<SecurityHarness />);
  await screen.findByRole("heading", { name: "Change Password" });
};

const setLocation = (search: string) => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      search,
      origin: "https://app.example.com",
      hostname: "app.example.com",
      assign: (value: string) => navigatedTo.push(value),
    },
  });
};

describe("SecuritySection Microsoft linking", () => {
  beforeEach(() => {
    linkState = {
      configured: true,
      linked: false,
      startStatus: 200,
      startBody: {
        link_token: "link-token-abc",
        authorize_path: "/auth/linked-identities/microsoft/authorize",
      },
    };
    navigatedTo = [];
    setLocation("");
    installFetchMock();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends nothing until the password and the confirmation are both given", async () => {
    await renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Connect Microsoft" }));

    const confirm = screen.getByRole("button", { name: "Confirm and continue" });
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Account password"), {
      target: { value: "Password123!" },
    });
    expect(confirm).toBeDisabled();
    expect(startRequests).toHaveLength(0);

    fireEvent.click(screen.getByRole("checkbox"));
    expect(confirm).toBeEnabled();
  });

  it("hands the browser to the provider only after the password is accepted", async () => {
    await renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Connect Microsoft" }));
    fireEvent.change(screen.getByLabelText("Account password"), {
      target: { value: "Password123!" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" }));

    await waitFor(() => expect(startRequests).toHaveLength(1));
    const [request] = startRequests;
    expect(request.method).toBe("POST");
    expect(JSON.parse(String(request.body))).toEqual({
      current_password: "Password123!",
      confirm: true,
    });

    await waitFor(() => expect(navigatedTo).toHaveLength(1));
    expect(navigatedTo[0]).toBe(
      "https://app.example.com/api/v1/auth/linked-identities/microsoft/authorize?link_token=link-token-abc"
    );
  });

  it("reports a rejected password and goes nowhere", async () => {
    linkState.startStatus = 400;
    linkState.startBody = { detail: "Current password is incorrect." };
    await renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Connect Microsoft" }));
    fireEvent.change(screen.getByLabelText("Account password"), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" }));

    expect(await screen.findByText("Current password is incorrect.")).toBeInTheDocument();
    expect(navigatedTo).toHaveLength(0);
  });

  it("offers no linking row where Microsoft sign-in is not configured", async () => {
    linkState.configured = false;
    await renderSection();

    await waitFor(() => expect(screen.getByRole("heading", { name: "Advanced Security" })));
    expect(screen.queryByText("Microsoft sign-in")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect Microsoft" })).not.toBeInTheDocument();
  });

  it("shows the connected state instead of the form once linked", async () => {
    linkState.linked = true;
    await renderSection();

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect Microsoft" })).not.toBeInTheDocument();
  });

  it("reads the outcome of the provider leg from the return query string", async () => {
    setLocation("?linked=microsoft");
    await renderSection();

    expect(
      await screen.findByText("Microsoft sign-in is now connected to this account.")
    ).toBeInTheDocument();
  });

  it("names the reason when the provider identity belongs to another account", async () => {
    setLocation("?link_error=identity_already_linked");
    await renderSection();

    expect(
      await screen.findByText(
        "That Microsoft account is already connected to another Qiko Signal account."
      )
    ).toBeInTheDocument();
  });
});
