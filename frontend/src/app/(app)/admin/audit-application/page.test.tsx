import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminAuditApplicationPage from "@/app/(app)/admin/audit-application/page";

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

describe("AdminAuditApplicationPage", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders dual-track runtime badges in the audit history list and forwards runtime filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/admin/audits?")) {
        return jsonResponse({
          audits: [
            {
              id: 15,
              user_id: 4,
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
          page: 1,
          page_size: 25,
          total: 1,
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AdminAuditApplicationPage />);

    expect(await screen.findByText("Brand Example")).toBeInTheDocument();
    const row = screen.getByText("Brand Example").closest("tr");
    expect(row).not.toBeNull();
    const rowQueries = within(row as HTMLElement);
    expect(rowQueries.getByText("Brand Example")).toBeInTheDocument();
    expect(rowQueries.getByText("brand")).toBeInTheDocument();
    // The row renders `Requested {getTierShort(...)}`, and TIER_SHORT maps
    // deep_judgment to "Deep". The uppercase look is CSS, which textContent does
    // not apply, so this matched the old long label rather than what renders.
    expect(
      rowQueries.getAllByText((_, node) => node?.textContent?.includes("Requested Deep") ?? false)
        .length
    ).toBeGreaterThan(0);
    expect(rowQueries.getByText("shadow dual track")).toBeInTheDocument();
    expect(rowQueries.getByText("Dual-track on")).toBeInTheDocument();
    expect(rowQueries.getByText("A 3 / B 2")).toBeInTheDocument();
    expect(rowQueries.getByText("track b judge unavailable")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Grounding profile filter"), {
      target: { value: "shadow_dual_track" },
    });
    fireEvent.change(screen.getByLabelText("Dual-track enabled filter"), {
      target: { value: "enabled" },
    });
    fireEvent.change(screen.getByLabelText("Fallback reason filter"), {
      target: { value: "judge" },
    });

    await waitFor(
      () => {
        const urls = fetchMock.mock.calls.map(([input]) => String(input));
        expect(urls.some((url) => url.startsWith("/api/admin/audits?"))).toBe(true);
        expect(urls.some((url) => url.includes("grounding_profile=shadow_dual_track"))).toBe(true);
        expect(urls.some((url) => url.includes("dual_track_grounding_enabled=true"))).toBe(true);
        expect(urls.some((url) => url.includes("fallback_reason=judge"))).toBe(true);
      },
      { timeout: 2000 }
    );
  });
});
