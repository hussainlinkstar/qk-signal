import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AuditTrailPage from "@/app/(app)/admin/audit-trail/page";

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

const jsonResponse = (payload: unknown) =>
  new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

describe("AuditTrailPage", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the audit execution trail and forwards dual-track filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/admin/action-logs?")) {
        return jsonResponse({
          items: [
            {
              id: 1,
              admin_user_id: 7,
              admin_email: "admin@example.com",
              action: "audit_viewed",
              target_type: "audit",
              target_id: "15",
              metadata: { section: "overview" },
              created_at: "2026-03-11T09:00:00Z",
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        });
      }
      if (url === "/api/admin/action-logs/summary") {
        return jsonResponse({
          total_actions: 1,
          actions_last_24h: 1,
          actions_last_7d: 1,
          top_actions: [{ label: "audit_viewed", count: 1 }],
          top_actors: [{ label: "admin@example.com", count: 1 }],
          top_target_types: [{ label: "audit", count: 1 }],
        });
      }
      if (url.startsWith("/api/admin/audits?")) {
        return jsonResponse({
          audits: [
            {
              id: 15,
              user_id: 2,
              user_email: "owner@example.com",
              url: "https://brand.example.com",
              audit_target_type: "brand",
              target_name: "Brand Example",
              target_url: "https://brand.example.com",
              geo_score: 80,
              seo_score: 78,
              aeo_score: 82,
              provider: "google",
              tier: "deep_judgment",
              requested_tier: "deep_judgment",
              grounding_profile: "shadow_dual_track",
              dual_track_grounding_enabled: true,
              fallback_reason: "track_b_judge_unavailable",
              track_a_claim_count: 3,
              track_b_claim_count: 2,
              dual_track_rollout_mode: "allowlist_enabled",
              dual_track_execution_mode: "shadow",
              created_at: "2026-03-11T10:00:00Z",
              sanitized_at: null,
              has_screenshot: false,
            },
          ],
          total: 1,
          page: 1,
          page_size: 25,
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AuditTrailPage />);

    /*
     * "Audit execution trail" is a static heading, so it is on screen in the
     * first commit, before the audits fetch has resolved. Waiting on it and then
     * querying the fetched rows synchronously asserts that the response landed
     * inside React's own act flush, which under parallel load it need not.
     * Each fetched value waits for its own commit instead.
     */
    expect(await screen.findByText("Audit execution trail")).toBeInTheDocument();
    expect(await screen.findByText("Brand Example")).toBeInTheDocument();
    expect(await screen.findByText("track b judge unavailable")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Audit URL fragment"), {
      target: { value: "brand.example.com" },
    });
    fireEvent.change(screen.getByLabelText("Grounding profile filter"), {
      target: { value: "shadow_dual_track" },
    });
    fireEvent.change(screen.getByLabelText("Dual-track enabled filter"), {
      target: { value: "enabled" },
    });
    fireEvent.change(screen.getByLabelText("Fallback reason filter"), {
      target: { value: "judge" },
    });

    await waitFor(() => {
      const auditUrls = fetchMock.mock.calls
        .map(([input]) => String(input))
        .filter((url) => url.startsWith("/api/admin/audits?"));

      expect(auditUrls.some((url) => url.includes("url_contains=brand.example.com"))).toBe(true);
      expect(auditUrls.some((url) => url.includes("grounding_profile=shadow_dual_track"))).toBe(
        true
      );
      expect(auditUrls.some((url) => url.includes("dual_track_grounding_enabled=true"))).toBe(true);
      expect(auditUrls.some((url) => url.includes("fallback_reason=judge"))).toBe(true);
    });
  });
});
