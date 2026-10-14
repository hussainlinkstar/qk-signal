import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({
  serverFetch: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

vi.mock("@/utils/server-fetch", () => ({ serverFetch: mocks.serverFetch }));
vi.mock("next/navigation", () => ({ notFound: mocks.notFound }));
vi.mock("@/app/(app)/admin/AdminShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div data-shell>{children}</div>,
}));

import AdminLayout from "@/app/(app)/admin/layout";

const ok = (role: string) => ({ ok: true, json: async () => ({ role }) });

/**
 * The admin bundle used to be downloaded by anyone who opened /admin. The
 * client guard refused to render it and the API returned 403, so no data
 * leaked, but the navigation for every internal tool shipped to the browser.
 */
describe("admin layout staff gate", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each(["admin", "moderator"])("renders the shell for %s", async (role) => {
    mocks.serverFetch.mockResolvedValue(ok(role));
    await AdminLayout({ children: null });
    expect(mocks.notFound).not.toHaveBeenCalled();
  });

  it.each(["user", "", "Admin "])("404s for a non-staff role: %j", async (role) => {
    mocks.serverFetch.mockResolvedValue(ok(role));
    await expect(AdminLayout({ children: null })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("404s when the session cannot be read, rather than failing open", async () => {
    mocks.serverFetch.mockResolvedValue({ ok: false, json: async () => ({}) });
    await expect(AdminLayout({ children: null })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(mocks.notFound).toHaveBeenCalled();
  });

  it("404s when the payload has no role at all", async () => {
    mocks.serverFetch.mockResolvedValue({ ok: true, json: async () => ({}) });
    await expect(AdminLayout({ children: null })).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
