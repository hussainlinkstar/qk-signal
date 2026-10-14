import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import { SocialLogins } from "@/components/auth/SocialLogins";

const originalLocation = window.location;
const assignMock = vi.fn();

describe("SocialLogins", () => {
  beforeEach(() => {
    assignMock.mockReset();
    // next/image resolves its src against window.location.href, so a partial
    // mock made every render throw "Invalid URL" from BrandLogo.
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

  it("routes to the Microsoft OAuth endpoint", () => {
    render(<SocialLogins />);

    fireEvent.click(screen.getByRole("button", { name: "Continue with Microsoft" }));

    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with LinkedIn" })).toBeInTheDocument();
    expect(assignMock).toHaveBeenCalledWith(
      "https://app.thothgraph.com/api/v1/auth/login/microsoft"
    );
  });

  it("ignores retired trial tokens for register flows", () => {
    // Only `search` differs from the shared mock in beforeEach; the rest is kept
    // so next/image can still resolve against a real href.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        ...window.location,
        search: "?trial_token=trial-token-123",
      },
    });

    render(<SocialLogins mode="register" />);

    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    expect(assignMock).toHaveBeenCalledWith("https://app.thothgraph.com/api/v1/auth/login/google");
  });
});
