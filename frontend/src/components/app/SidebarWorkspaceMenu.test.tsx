import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@/i18n";

const store = new Map<string, string>();
beforeEach(() => {
  store.clear();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      get length() {
        return store.size;
      },
      clear: () => store.clear(),
      getItem: (key: string) => store.get(key) ?? null,
      key: (index: number) => Array.from(store.keys())[index] ?? null,
      removeItem: (key: string) => store.delete(key),
      setItem: (key: string, value: string) => store.set(key, value),
    } satisfies Storage,
  });
  pathname = "/dashboard";
});

const authState = {
  getToken: vi.fn(async () => "token-123"),
  isSignedIn: true,
  user: { subscription_plan: "plan_standard", name: "Razvan Baba" },
};

const push = vi.fn();
const refresh = vi.fn();
let pathname = "/dashboard";

vi.mock("@/components/auth/custom-auth", () => ({ useAuth: () => authState }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push, refresh }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/services/workspaceService", () => ({
  fetchUserWorkspaces: vi.fn(async () => [
    { id: 1, name: "Acme Workspace", role: "OWNER", is_owner: true, project_count: 2 },
    { id: 2, name: "Beta Workspace", role: "ADMIN", is_owner: false, project_count: 1 },
  ]),
  fetchWorkspaceProjects: vi.fn(async () => [
    { id: 9, name: "Northwind Hotels", domain_url: "https://northwind-hotels.com" },
    { id: 10, name: "Coastline Resorts", domain_url: "https://coastline.example" },
  ]),
}));

import SidebarWorkspaceMenu from "./SidebarWorkspaceMenu";
import MobileDashboardDrawer from "./MobileDashboardDrawer";
import { ACTIVE_WORKSPACE_KEY } from "@/components/app/WorkspaceSwitcher";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});
const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

const renderMenu = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);

afterEach(() => {
  vi.clearAllMocks();
});

const openMenu = async (label = /workspace and account menu/i) => {
  fireEvent.click(await screen.findByRole("button", { name: label }));
};

describe("SidebarWorkspaceMenu", () => {
  it("dismisses the nested account menu before closing the mobile drawer", async () => {
    renderMenu(
      <MobileDashboardDrawer
        primarySections={[]}
        isProjectContext={false}
        isStaff={false}
        email="preview@example.com"
        onLogout={vi.fn()}
      />
    );
    const drawerTrigger = screen.getByRole("button", { name: "Open dashboard menu" });
    fireEvent.click(drawerTrigger);
    await openMenu();
    const accountTrigger = screen.getByRole("button", { name: "Workspace and account menu" });
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Dashboard navigation" })).toBeInTheDocument();
    expect(accountTrigger).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(drawerTrigger).toHaveFocus();
  });

  it("labels the switcher by scope and shows the signed-in identity above Sign out", async () => {
    const onLogout = vi.fn();
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={onLogout} />);

    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(await screen.findByText("Acme Workspace")).toBeInTheDocument();

    await openMenu();

    const menu = screen.getByRole("menu");
    expect(await within(menu).findByText("Razvan Baba")).toBeInTheDocument();
    expect(within(menu).getByText("razvan@qiko.ai")).toBeInTheDocument();

    const signOut = await screen.findByRole("menuitem", { name: /sign out/i });
    fireEvent.click(signOut);
    await waitFor(() => expect(onLogout).toHaveBeenCalledTimes(1));
  });

  it("persists the picked workspace and refreshes without a no-op navigation", async () => {
    store.set(ACTIVE_WORKSPACE_KEY, "1");
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={vi.fn()} />);

    await openMenu();
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Beta Workspace/i }));

    await waitFor(() => expect(store.get(ACTIVE_WORKSPACE_KEY)).toBe("2"));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
  });

  it("keeps an earlier workspace listed and reachable after a newer one became active", async () => {
    // SIGV2-1158: creating a workspace only changes the active scope. The
    // workspace set up before it must stay in the switcher, and going back to
    // it must drop the other workspace's cached data instead of replaying it.
    store.set(ACTIVE_WORKSPACE_KEY, "2");
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={vi.fn()} />);

    expect(await screen.findByText("Beta Workspace")).toBeInTheDocument();

    await openMenu();
    const previous = await screen.findByRole("menuitemradio", { name: /Acme Workspace/i });
    expect(previous).toHaveAttribute("aria-checked", "false");

    fireEvent.click(previous);

    await waitFor(() => expect(store.get(ACTIVE_WORKSPACE_KEY)).toBe("1"));
    expect(refresh).toHaveBeenCalled();
    expect(invalidateSpy).toHaveBeenCalled();
    expect(await screen.findByText("Acme Workspace")).toBeInTheDocument();
  });

  it("navigates to the dashboard when switching from another route", async () => {
    pathname = "/dashboard/projects/9/seo";
    store.set(ACTIVE_WORKSPACE_KEY, "1");
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={vi.fn()} />);

    await openMenu();
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Beta Workspace/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
  });

  it("project scope: shows the current project, lists only authorised projects, no invented entries", async () => {
    pathname = "/dashboard/projects/9";
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={vi.fn()} projectScope />);

    // The approved `.ssw-btn` shows the project's bare domain, name only as
    // fallback; there is no avatar and no second line.
    expect(await screen.findByText("northwind-hotels.com")).toBeInTheDocument();
    expect(screen.getByText("Project", { selector: "p" })).toBeInTheDocument();

    await openMenu(/project and account menu/i);

    const radios = await screen.findAllByRole("menuitemradio");
    expect(radios).toHaveLength(2);
    expect(screen.queryByRole("menuitem", { name: /add project/i })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: /northwind-hotels.com/i })).toHaveAttribute(
      "aria-checked",
      "true"
    );
  });

  it("project scope: switching invalidates cached queries and refreshes the route", async () => {
    pathname = "/dashboard/projects/9";
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={vi.fn()} projectScope />);

    await openMenu(/project and account menu/i);
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /coastline.example/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard/projects/10"));
    expect(refresh).toHaveBeenCalled();
    expect(invalidateSpy).toHaveBeenCalled();
  });

  it("project scope: a project absent from the authorised list is never shown as selected", async () => {
    pathname = "/dashboard/projects/999";
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={vi.fn()} projectScope />);

    expect(await screen.findByText("Project", { selector: "button span" })).toBeInTheDocument();
    await openMenu(/project and account menu/i);
    for (const radio of await screen.findAllByRole("menuitemradio")) {
      expect(radio).toHaveAttribute("aria-checked", "false");
    }
  });

  it("cycles focus through the menu with the arrow keys and restores it on Escape", async () => {
    store.set(ACTIVE_WORKSPACE_KEY, "1");
    renderMenu(<SidebarWorkspaceMenu email="razvan@qiko.ai" onLogout={vi.fn()} />);

    const trigger = await screen.findByRole("button", { name: /workspace and account menu/i });
    fireEvent.click(trigger);
    const menu = await screen.findByRole("menu");
    const first = await screen.findByRole("menuitemradio", { name: /Acme Workspace/i });
    first.focus();

    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitemradio", { name: /Beta Workspace/i })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: /sign out/i })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(screen.getByRole("menuitemradio", { name: /Beta Workspace/i })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveFocus();
  });
});
