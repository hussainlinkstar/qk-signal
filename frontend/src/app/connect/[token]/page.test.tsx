import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MagicLinkConnectPage from "@/app/connect/[token]/page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok-abc" }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("motion/react", () => ({
  motion: new Proxy(
    {},
    {
      get:
        () =>
        ({ children, ...rest }: { children?: React.ReactNode }) => <div {...rest}>{children}</div>,
    }
  ),
}));

const validPayload = {
  valid: true,
  token: "tok-abc",
  project_id: 42,
  workspace_id: 1,
  project_name: "Client Project",
  domain_url: "https://client.example",
  expires_at: "2026-04-01T00:00:00.000Z",
  is_used: false,
  connection_state: "pending",
  providers: [
    { provider: "google", connected: false, connected_at: null },
    { provider: "bing", connected: true, connected_at: "2026-03-01T10:00:00.000Z" },
  ],
};

const fetchMock = vi.fn();

describe("MagicLinkConnectPage (signal-light reskin)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => validPayload,
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders on the light Signal canvas with panel cards, not the dark split-screen", async () => {
    render(<MagicLinkConnectPage />);
    await screen.findByText("Client Project");

    const main = document.querySelector("main")!;
    expect(main.className).toContain("signal-canvas");
    // The approved vocabulary is the light panel card; the old dark
    // split-screen (aside + orbs + white text) must be gone.
    expect(main.querySelector("aside")).toBeNull();
    expect(document.body.innerHTML).not.toContain("bg-linear-to-br");
    expect(screen.getByRole("heading", { level: 1 }).className).not.toContain("text-white");
  });

  it("renders providers as approved .conn rows with a badge-ok for connected", async () => {
    render(<MagicLinkConnectPage />);
    await screen.findByText("Client Project");

    const bingRow = screen.getByText("Microsoft").closest("div[class*='items-center']")!;
    const badge = screen.getByText("Connected");
    expect(badge.className).toContain("bg-(--good-s)");
    expect(bingRow).toBeTruthy();

    const googleRow = screen.getByText("Google").closest("div[class*='items-center']")!;
    expect(googleRow.className).toContain("gap-3");
  });

  it("keeps every capability: authorize action, project card, expiry, trust signals", async () => {
    render(<MagicLinkConnectPage />);
    await screen.findByText("Client Project");

    expect(screen.getByRole("button", { name: /Authorize/i })).toBeInTheDocument();
    expect(screen.getByText(/Expires/)).toBeInTheDocument();
    expect(screen.getByText("End-to-end encryption")).toBeInTheDocument();
    expect(screen.getByText("Revoke anytime")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to Qiko Signal/i })).toHaveAttribute(
      "href",
      "/login"
    );
    expect(screen.getByText(/1 of 2 connected/)).toBeInTheDocument();
  });

  it("renders the invalid-link state in the light vocabulary", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ...validPayload, valid: false, connection_state: "expired" }),
    });
    render(<MagicLinkConnectPage />);
    await waitFor(() => expect(screen.getByText("Link unavailable")).toBeInTheDocument());
    expect(document.body.innerHTML).not.toContain("text-amber-200");
  });
});
