import React from "react";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { tEn } from "@/test/i18nEn";
import DataRightsSection from "@/app/(app)/dashboard/account-settings/components/DataRightsSection";
import { useAccountSettings } from "@/app/(app)/dashboard/account-settings/useAccountSettings";

/**
 * SIGV2-1131.
 *
 * Deleting an account is irreversible, and this route once fired it from a
 * bare onClick with no confirmation of any kind. SIGV2-1039 added the
 * approved dialog but nothing held it in place, so these tests are the guard:
 * every assertion below is about the request NOT being sent. A future change
 * that reconnects the destructive button straight to the delete action, or
 * calls the delete action from somewhere that never showed the dialog, has to
 * turn one of these red to land.
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

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => authState,
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

/** Every DELETE sent to the account endpoint, in order. */
let deletionRequests: RequestInit[] = [];

const installFetchMock = () => {
  deletionRequests = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    if (url === "/api/users/me" && method === "DELETE") {
      deletionRequests.push(init ?? {});
      return new Response(JSON.stringify({ message: "Account data deleted successfully." }), {
        status: 200,
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

/**
 * The real hook behind the real section, so the confirmation gate under test
 * is the one that ships rather than a stub of it.
 */
const DataRightsHarness: React.FC = () => {
  const settings = useAccountSettings();
  return <DataRightsSection settings={settings} />;
};

const renderSection = async () => {
  render(<DataRightsHarness />);
  return screen.findByRole("button", { name: tEn("myProfileData.delete.action") });
};

const dialog = () => screen.getByRole("dialog");

describe("DataRightsSection account deletion", () => {
  beforeEach(() => {
    authState.logout.mockClear();
    installFetchMock();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("asks for confirmation instead of deleting when the delete button is pressed", async () => {
    const deleteButton = await renderSection();

    fireEvent.click(deleteButton);

    expect(
      await screen.findByRole("heading", { name: tEn("myProfileData.delete.dialogTitle") })
    ).toBeInTheDocument();
    expect(deletionRequests).toHaveLength(0);
    expect(authState.logout).not.toHaveBeenCalled();
  });

  it("states what is retained, and why, inside the confirmation step itself", async () => {
    const deleteButton = await renderSection();

    fireEvent.click(deleteButton);

    const confirmation = within(await screen.findByRole("dialog"));
    expect(confirmation.getByText(tEn("myProfileData.delete.dialogBodyOne"))).toBeInTheDocument();
    expect(confirmation.getByText(tEn("myProfileData.delete.dialogBodyTwo"))).toBeInTheDocument();
  });

  it("sends nothing when the confirmation is cancelled", async () => {
    const deleteButton = await renderSection();

    fireEvent.click(deleteButton);
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: tEn("myProfileData.delete.cancel"),
      })
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(deletionRequests).toHaveLength(0);
    expect(authState.logout).not.toHaveBeenCalled();
  });

  it("sends the deletion only after the confirmation is accepted", async () => {
    const deleteButton = await renderSection();

    fireEvent.click(deleteButton);
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: tEn("myProfileData.delete.action"),
      })
    );

    await waitFor(() => expect(deletionRequests).toHaveLength(1));
    const [request] = deletionRequests;
    expect(request.method).toBe("DELETE");
    expect(JSON.parse(String(request.body))).toEqual({ confirm: true });
    await waitFor(() => expect(authState.logout).toHaveBeenCalledTimes(1));
  });

  it("re-arms the confirmation, so one acceptance cannot authorise a second deletion", async () => {
    const deleteButton = await renderSection();

    fireEvent.click(deleteButton);
    fireEvent.click(
      within(dialog()).getByRole("button", { name: tEn("myProfileData.delete.action") })
    );
    await waitFor(() => expect(deletionRequests).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: tEn("myProfileData.delete.action") }));

    expect(
      await screen.findByRole("heading", { name: tEn("myProfileData.delete.dialogTitle") })
    ).toBeInTheDocument();
    expect(deletionRequests).toHaveLength(1);
  });

  it("refuses a deletion that never reached the confirmation step", async () => {
    const { result } = renderHook(() => useAccountSettings());
    await waitFor(() => expect(result.current.isBootLoading).toBe(false));

    await act(async () => {
      await result.current.handleDelete();
    });

    expect(deletionRequests).toHaveLength(0);
    expect(authState.logout).not.toHaveBeenCalled();
    expect(result.current.isDeleting).toBe(false);
  });

  it("deletes once the confirmation step has been opened on the hook", async () => {
    const { result } = renderHook(() => useAccountSettings());
    await waitFor(() => expect(result.current.isBootLoading).toBe(false));

    act(() => result.current.openDeleteConfirmation());
    await waitFor(() => expect(result.current.isDeleteConfirmationOpen).toBe(true));
    await act(async () => {
      await result.current.handleDelete();
    });

    expect(deletionRequests).toHaveLength(1);
  });
});
