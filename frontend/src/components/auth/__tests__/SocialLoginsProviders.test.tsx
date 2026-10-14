import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import { SocialLogins } from "@/components/auth/SocialLogins";

const originalLocation = window.location;
const assignMock = vi.fn();

describe("SocialLogins provider UX", () => {
  beforeEach(() => {
    assignMock.mockReset();
    // next/image resolves its src against window.location.href, so a mock with
    // only hostname and origin made every render throw "Invalid URL" from
    // BrandLogo before any assertion could run. The full shape is spelled out
    // rather than partially stubbed.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        hostname: "app.thothgraph.com",
        origin: "https://app.thothgraph.com",
        href: "https://app.thothgraph.com/",
        protocol: "https:",
        host: "app.thothgraph.com",
        port: "",
        pathname: "/",
        search: "",
        hash: "",
        assign: assignMock,
        replace: vi.fn(),
        reload: vi.fn(),
        toString: () => "https://app.thothgraph.com/",
      },
    });
  });

  afterAll(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("shows provider action labels without the redundant trust copy block", () => {
    render(<SocialLogins />);

    expect(
      screen.queryByText("Single sign-on with your existing work account.")
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with Microsoft" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with LinkedIn" })).toBeInTheDocument();
  });

  it("sets loading state on the selected provider button", () => {
    render(<SocialLogins />);

    fireEvent.click(screen.getByRole("button", { name: "Continue with Microsoft" }));

    expect(assignMock).toHaveBeenCalledWith(
      "https://app.thothgraph.com/api/v1/auth/login/microsoft"
    );
    expect(screen.getByRole("button", { name: "Continue with Microsoft" })).toBeDisabled();
    expect(screen.getByText("Completing sign-in...")).toBeInTheDocument();
  });

  it("renders the compact icon row with passkey when requested", () => {
    const passkeyHandler = vi.fn();

    render(
      <SocialLogins
        variant="icon-row"
        includePasskey
        label="login with"
        onPasskeyClick={passkeyHandler}
      />
    );

    expect(screen.getByRole("button", { name: "Continue with Microsoft" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with LinkedIn" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in with passkey/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /sign in with passkey/i }));

    expect(passkeyHandler).toHaveBeenCalledTimes(1);
  });
});
