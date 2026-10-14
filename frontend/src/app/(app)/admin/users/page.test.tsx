import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminUsersPage from "@/app/(app)/admin/users/page";
import { PageHeaderHarness } from "@/test/pageHeaderHarness";

/* Renders the page's registered `.top` actions like AdminShell does. */
const renderPage = () =>
  render(
    <PageHeaderHarness>
      <AdminUsersPage />
    </PageHeaderHarness>
  );

/*
 * The page lifts its header actions into the shell from an effect, so the
 * registered "Invite user" button is always one commit behind the table it sits
 * above: the fetch resolves, the table and `isLoading: false` commit together,
 * and only the passive effect that follows re-registers the button in its
 * enabled form. Waiting on the table therefore proves nothing about the button.
 * React schedules that passive effect on a task while the MutationObserver that
 * resolves `findBy*` runs on a microtask, so under parallel load the table can
 * be observable while the header still holds the disabled render. Clicking a
 * disabled button dispatches nothing, the modal never opens, and the test fails
 * on a heading it was never going to see. Synchronise on the control being
 * clicked instead.
 */
const clickInviteAction = async () => {
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /invite user/i })).toBeEnabled();
  });
  fireEvent.click(screen.getByRole("button", { name: /invite user/i }));
};

const authState = {
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
};

const adminAccessState = {
  isAdmin: true,
  isLoading: false,
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/components/admin/AdminGuardProvider", () => ({
  useAdminAccess: () => adminAccessState,
}));

const toastMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  loading: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: toastMock,
}));

const jsonResponse = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const usersListResponse = {
  users: [
    {
      id: 1,
      email: "existing@example.com",
      role: "user",
      credits: 5,
      notifications_enabled: true,
      plan: "plan_starter",
      subscription_status: null,
      audit_count: 0,
    },
  ],
  page: 1,
  page_size: 25,
  total: 1,
};

describe("AdminUsersPage invite flow", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
    toastMock.success.mockClear();
    toastMock.error.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens the invite modal, submits the form, and refreshes the list on success", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/api/admin/users?")) {
        return jsonResponse(usersListResponse);
      }
      if (url === "/api/admin/users/invite" && init?.method === "POST") {
        return jsonResponse(
          {
            user_id: 42,
            email: "new.client@example.com",
            role: "user",
            invited: true,
            email_queued: true,
            invitation_url: null,
          },
          201
        );
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    renderPage();

    expect(await screen.findByText("existing@example.com")).toBeInTheDocument();

    await clickInviteAction();

    expect(await screen.findByRole("heading", { name: "Invite user" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("name@company.com"), {
      target: { value: "new.client@example.com" },
    });

    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    await waitFor(() => {
      const inviteCalls = fetchMock.mock.calls.filter(
        ([reqInput]) => String(reqInput) === "/api/admin/users/invite"
      );
      expect(inviteCalls).toHaveLength(1);
    });

    const [, inviteInit] = fetchMock.mock.calls.find(
      ([reqInput]) => String(reqInput) === "/api/admin/users/invite"
    )!;
    expect(JSON.parse(String(inviteInit?.body))).toEqual({
      email: "new.client@example.com",
      name: null,
      role: "user",
    });

    await waitFor(() => {
      expect(toastMock.success).toHaveBeenCalledWith(
        "Invitation email sent to new.client@example.com."
      );
    });

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Invite user" })).not.toBeInTheDocument();
    });
  });

  it("shows an inline error and keeps the modal open when the email already exists", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/api/admin/users?")) {
        return jsonResponse(usersListResponse);
      }
      if (url === "/api/admin/users/invite" && init?.method === "POST") {
        return jsonResponse({ detail: "A user with this email already exists." }, 409);
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    renderPage();

    expect(await screen.findByText("existing@example.com")).toBeInTheDocument();

    await clickInviteAction();
    expect(await screen.findByRole("heading", { name: "Invite user" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("name@company.com"), {
      target: { value: "existing@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    expect(await screen.findByText("A user with this email already exists.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Invite user" })).toBeInTheDocument();
    expect(toastMock.success).not.toHaveBeenCalled();
  });
});

describe("AdminUsersPage package editing", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const installUserFetch = (plan: string) => {
    const user = { ...usersListResponse.users[0], plan };
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/api/admin/users?")) {
        return jsonResponse({ ...usersListResponse, users: [user] });
      }
      if (url === "/api/admin/users/1" && init?.method === "PATCH") {
        return jsonResponse({ user });
      }
      if (url === "/api/admin/users/1") {
        return jsonResponse({
          user,
          audit_summary: { total: 0, last_audit_at: null, last_audit_url: null },
          subscription_summary: {
            plan,
            status: null,
            current_period_end: null,
            cancel_at_period_end: null,
            stripe_customer_id: null,
            stripe_subscription_id: null,
          },
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });
  };

  const openEdit = async () => {
    renderPage();
    await screen.findByText("existing@example.com");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Edit User" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit User" }));
    return screen.findByRole("dialog", { name: "Edit user" });
  };

  it("offers exactly the four active public packages", async () => {
    installUserFetch("plan_starter");
    const dialog = await openEdit();
    const select = within(dialog).getAllByRole("combobox")[1] as HTMLSelectElement;

    expect(
      Array.from(select.options)
        .filter((option) => option.value.startsWith("plan_"))
        .map((option) => [option.value, option.textContent])
    ).toEqual([
      ["plan_starter", "Starter"],
      ["plan_standard", "Standard"],
      ["plan_specialist", "Specialist"],
      ["plan_executive", "Executive"],
    ]);
  });

  it("allows an unrelated legacy trial edit without submitting a replacement package", async () => {
    const fetchMock = installUserFetch("plan_agency_trial");
    const dialog = await openEdit();
    const [roleSelect, planSelect] = within(dialog).getAllByRole("combobox");
    expect(
      within(planSelect).queryByRole("option", { name: "Agency Trial" })
    ).not.toBeInTheDocument();
    fireEvent.change(roleSelect, { target: { value: "moderator" } });
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true);
    });
    const [, init] = fetchMock.mock.calls.find(([, request]) => request?.method === "PATCH")!;
    expect(JSON.parse(String(init?.body))).toEqual({
      role: "moderator",
      notifications_enabled: true,
    });
  });

  it("submits an explicitly selected replacement for a legacy trial", async () => {
    const fetchMock = installUserFetch("plan_agency_trial");
    const dialog = await openEdit();
    fireEvent.change(within(dialog).getAllByRole("combobox")[1], {
      target: { value: "plan_standard" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true);
    });
    const [, init] = fetchMock.mock.calls.find(([, request]) => request?.method === "PATCH")!;
    expect(JSON.parse(String(init?.body)).plan_type).toBe("plan_standard");
  });
});
