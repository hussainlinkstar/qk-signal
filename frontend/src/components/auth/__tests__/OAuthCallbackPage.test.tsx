import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OAuthCallbackPage from "@/app/auth/callback/page";

const setSessionMock = vi.fn();
const fetchMock = vi.fn();
const originalLocation = window.location;
const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    setSession: setSessionMock,
  }),
}));

vi.mock("@/components/signal/SignalBrandLockup", () => ({
  default: () => <div>Logo</div>,
}));

describe("OAuthCallbackPage", () => {
  beforeEach(() => {
    setSessionMock.mockReset();
    fetchMock.mockReset();
    replaceMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    setUrl();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  afterAll(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  const setUrl = (query = "") => {
    const url = new URL(`https://app.thothgraph.com/auth/callback${query}`);
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        ...url,
        href: url.href,
        origin: url.origin,
        pathname: url.pathname,
        search: url.search,
        replace: replaceMock,
      },
    });
  };

  it("renders secure handoff progress stages", async () => {
    setSessionMock.mockImplementation(() => new Promise(() => {}));
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        authenticated: true,
      }),
    });

    setUrl("?code=oauth-code");
    render(<OAuthCallbackPage />);

    expect(await screen.findByText("Completing Sign-In")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
  });

  it("handles provider_error with a recovery CTA", async () => {
    setUrl("?error=provider_error&provider=google");

    render(<OAuthCallbackPage />);

    expect(await screen.findByText("Provider session could not connect")).toBeInTheDocument();
    expect(
      screen.getByText("Your Google session couldn't connect. Try again or use email sign-in.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Try Sign In Again" })).toHaveAttribute(
      "href",
      "/login"
    );
  });

  /* SIGV2-1171. This card used to offer "Try Sign In Again" and "Use Email
     Sign In" side by side for provider_error and expired_code, and both went
     to /login: one action wearing two labels, which reads as a choice the
     customer has to understand and does not have. The intent of the old test
     was "the recovery route exists"; it is now "the recovery route exists and
     there is exactly one of it". Email sign-in is a form on /login, not a
     separate destination, and the description already says so. */
  it("offers one recovery route for provider_error, not two that go to the same place", async () => {
    setUrl("?error=provider_error&provider=google");

    render(<OAuthCallbackPage />);
    await screen.findByText("Provider session could not connect");

    const loginLinks = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href") === "/login");
    expect(loginLinks).toHaveLength(1);
    expect(loginLinks[0]).toHaveAccessibleName("Try Sign In Again");
    expect(screen.queryByRole("link", { name: "Use Email Sign In" })).toBeNull();
  });

  it("handles expired_code recovery state", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    });
    setUrl("?code=expired");

    render(<OAuthCallbackPage />);

    expect(await screen.findByText("Sign-in link expired")).toBeInTheDocument();
    expect(
      screen.getByText("This sign-in link expired. Return to Sign In and try again.")
    ).toBeInTheDocument();
    const loginLinks = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href") === "/login");
    expect(loginLinks).toHaveLength(1);
  });

  it("handles invalid_state when callback code is missing", async () => {
    setUrl("?state=missing");

    render(<OAuthCallbackPage />);

    await waitFor(() => {
      expect(screen.getByText("Unexpected sign-in interruption")).toBeInTheDocument();
    });
    expect(
      screen.getByText("Unexpected error during sign-in. Please try again.")
    ).toBeInTheDocument();
    // Two genuinely different destinations stay two actions: retry the
    // sign-in, or create the account that does not exist yet.
    expect(screen.getByRole("link", { name: "Try Sign In Again" })).toHaveAttribute(
      "href",
      "/login"
    );
    expect(screen.getByRole("link", { name: "Create Account" })).toHaveAttribute(
      "href",
      "/register"
    );
  });

  it("navigates with a full document redirect after session handoff completes", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        authenticated: true,
      }),
    });
    setSessionMock.mockResolvedValue(undefined);

    setUrl("?code=oauth-code");
    render(<OAuthCallbackPage />);

    await waitFor(() => {
      expect(setSessionMock).toHaveBeenCalledTimes(1);
      expect(replaceMock).toHaveBeenCalledWith("/dashboard");
    });
  });
});
