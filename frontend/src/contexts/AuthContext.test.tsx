import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import authService from "@/services/auth.service";
import { TokenManager } from "@/utils/token-manager";

const routerPush = vi.fn();
const usePathnameMock = vi.fn(() => "/dashboard");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  usePathname: () => usePathnameMock(),
}));

vi.mock("@/services/auth.service", () => ({
  default: {
    getCurrentUser: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

describe("AuthProvider terminal auth failures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usePathnameMock.mockReturnValue("/dashboard");
    vi.spyOn(TokenManager, "getAccessTokenWithFallback").mockResolvedValue(null);
    vi.spyOn(TokenManager, "ensureSession").mockResolvedValue(true);
    vi.spyOn(TokenManager, "clearTokens").mockImplementation(() => undefined);
  });

  it("does not attempt a profile load when no cookie-backed session exists", async () => {
    render(
      <AuthProvider>
        <div>auth</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(authService.getCurrentUser).not.toHaveBeenCalled();
      expect(TokenManager.clearTokens).not.toHaveBeenCalled();
      expect(authService.logout).not.toHaveBeenCalled();
    });
  });

  it("keeps the session alive when the user profile can be loaded from cookie-backed auth", async () => {
    vi.spyOn(TokenManager, "getAccessTokenWithFallback").mockResolvedValue("__cookie_session__");
    vi.mocked(authService.getCurrentUser).mockResolvedValue({
      id: "1",
      email: "user@example.com",
      name: "User",
      role: "admin" as any,
      permissions: [],
      subscription_plan: "plan_specialist",
    });

    render(
      <AuthProvider>
        <div>auth</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(authService.getCurrentUser).toHaveBeenCalledTimes(1);
      expect(TokenManager.clearTokens).not.toHaveBeenCalled();
    });
  });

  it("clears local tokens when the user profile fetch fails", async () => {
    vi.spyOn(TokenManager, "getAccessTokenWithFallback").mockResolvedValue("__cookie_session__");
    vi.mocked(authService.getCurrentUser).mockRejectedValue(new Error("nope"));

    render(
      <AuthProvider>
        <div>auth</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(TokenManager.clearTokens).toHaveBeenCalledTimes(1);
      expect(authService.logout).not.toHaveBeenCalled();
    });
  });

  it("clears auth state and redirects to login on explicit logout broadcasts", async () => {
    vi.spyOn(TokenManager, "getAccessTokenWithFallback").mockResolvedValue("__cookie_session__");
    vi.mocked(authService.getCurrentUser).mockResolvedValue({
      id: "1",
      email: "user@example.com",
      name: "User",
      role: "admin" as any,
      permissions: [],
      subscription_plan: "plan_starter",
    });
    const clearTokensSpy = vi
      .spyOn(TokenManager, "clearTokens")
      .mockImplementation(() => undefined);

    render(
      <AuthProvider>
        <div>auth</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(authService.getCurrentUser).toHaveBeenCalledTimes(1);
    });

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "auth_logout", newValue: String(Date.now()) })
      );
    });

    await waitFor(() => {
      expect(clearTokensSpy).toHaveBeenCalledTimes(1);
      expect(routerPush).toHaveBeenCalledWith("/login");
    });
  });

  it("does not redirect when already on the login route", async () => {
    usePathnameMock.mockReturnValue("/login");
    vi.spyOn(TokenManager, "getAccessTokenWithFallback").mockResolvedValue("__cookie_session__");
    vi.mocked(authService.getCurrentUser).mockResolvedValue({
      id: "1",
      email: "user@example.com",
      name: "User",
      role: "admin" as any,
      permissions: [],
      subscription_plan: "plan_starter",
    });

    render(
      <AuthProvider>
        <div>auth</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(authService.getCurrentUser).toHaveBeenCalledTimes(1);
    });

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "auth_logout", newValue: String(Date.now()) })
      );
    });

    await waitFor(() => {
      expect(routerPush).not.toHaveBeenCalled();
    });
  });

  it("skips profile bootstrap when no session can be ensured", async () => {
    vi.spyOn(TokenManager, "getAccessTokenWithFallback").mockResolvedValue(null);

    render(
      <AuthProvider>
        <div>auth</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(authService.getCurrentUser).not.toHaveBeenCalled();
    });

    expect(TokenManager.clearTokens).not.toHaveBeenCalled();
  });

  /* ---------------------------------------------------------------------- */
  /*  SIGV2-1152                                                            */
  /* ---------------------------------------------------------------------- */

  it("hands every render the same getToken reference", async () => {
    // `getToken` is a `useCallback(..., [])` and consumers depend on that.
    // Unwrapping it is an unbounded remount loop in a real browser, not a style
    // regression, so the identity is pinned here rather than left implicit.
    const IDENTITY_CONTRACT =
      "AuthContext.getToken changed identity between renders. It must stay " +
      "useCallback(..., []): consumers put it in dependency arrays, so a new " +
      "reference per render re-runs their effects on every render, and an effect " +
      "that also sets state then renders again, forever. The known consumer is " +
      "the admin plans page (src/app/(app)/admin/plans/page.tsx), whose fetchAll " +
      "useCallback depends on [getToken] and whose mount effect depends on " +
      "[fetchAll]: it remounts in a loop and hangs the tab (SIGV2-1152).";

    vi.spyOn(TokenManager, "getAccessTokenWithFallback").mockResolvedValue("__cookie_session__");
    vi.mocked(authService.getCurrentUser).mockResolvedValue({
      id: "1",
      email: "user@example.com",
      name: "User",
      role: "admin" as any,
      permissions: [],
      subscription_plan: "plan_specialist",
    });

    const seen: Array<ReturnType<typeof useAuth>["getToken"]> = [];
    const GetTokenProbe = () => {
      const { getToken, isLoading } = useAuth();
      seen.push(getToken);
      return <span data-testid="probe">{isLoading ? "loading" : "ready"}</span>;
    };

    const { rerender } = render(
      <AuthProvider>
        <GetTokenProbe />
      </AuthProvider>
    );

    // The mount load settles, so the provider re-renders with new auth state.
    await waitFor(() => {
      expect(screen.getByTestId("probe")).toHaveTextContent("ready");
    });

    // A fresh element tree re-renders the provider while changing no auth state
    // at all, which is the case a dropped useCallback breaks.
    rerender(
      <AuthProvider>
        <GetTokenProbe />
      </AuthProvider>
    );

    expect(seen.length).toBeGreaterThan(2);
    for (const getToken of seen) {
      expect(getToken, IDENTITY_CONTRACT).toBe(seen[0]);
    }
  });
});
