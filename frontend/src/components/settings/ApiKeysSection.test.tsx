import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ApiKeysSection from "@/components/settings/ApiKeysSection";
import { createApiKey, fetchApiKeys, revokeApiKey } from "@/services/apiKeyService";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/services/apiKeyService", () => ({
  fetchApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));

describe("ApiKeysSection", () => {
  const getAuthHeaders = vi.fn(async () => ({ Authorization: "Bearer token-123" }));

  beforeEach(() => {
    getAuthHeaders.mockClear();
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_specialist",
      api_access_enabled: true,
      mcp_access_enabled: true,
      developer_hub_url: "/dashboard/developer",
    });
    vi.mocked(createApiKey).mockResolvedValue({
      api_key: "stx_live_createdkey0123456789abcdef",
      developer_hub_url: "/dashboard/developer",
      item: {
        id: 9,
        name: "Warehouse Export",
        key_prefix: "stx_live_",
        key_last_four: "cdef",
        scopes: ["audit:read", "audit:write"],
        is_active: true,
        created_at: "2026-03-03T11:00:00Z",
        last_used_at: null,
        revoked_at: null,
      },
    });
    vi.mocked(revokeApiKey).mockResolvedValue({
      revoked: true,
      item: {
        id: 9,
        name: "Warehouse Export",
        key_prefix: "stx_live_",
        key_last_four: "cdef",
        scopes: ["audit:read", "audit:write"],
        is_active: false,
        created_at: "2026-03-03T11:00:00Z",
        last_used_at: null,
        revoked_at: "2026-03-03T11:30:00Z",
      },
    });
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it("creates an API key and shows the one-time secret", async () => {
    render(<ApiKeysSection getAuthHeaders={getAuthHeaders} />);

    await screen.findByText("API Keys");
    await waitFor(() => {
      expect(screen.getByLabelText("Key Name")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Key Name"), {
      target: { value: "Warehouse Export" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create api key/i }));

    await waitFor(() => {
      expect(createApiKey).toHaveBeenCalledWith(
        { name: "Warehouse Export" },
        { Authorization: "Bearer token-123" }
      );
    });

    expect(await screen.findByText("Copy This Key Now")).toBeInTheDocument();
    expect(screen.getByText("stx_live_createdkey0123456789abcdef")).toBeInTheDocument();
    expect(
      screen.getByText("API key created. Copy it now because it will not be shown again.")
    ).toBeInTheDocument();
  });

  it("shows the plan lock banner when API access is unavailable", async () => {
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_standard",
      api_access_enabled: false,
      mcp_access_enabled: true,
      developer_hub_url: "/dashboard/developer",
    });

    render(<ApiKeysSection getAuthHeaders={getAuthHeaders} />);

    expect(await screen.findByText("Plan Upgrade Required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create api key/i })).toBeDisabled();
  });
});
