import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminAuditDetailPage from "@/app/(app)/admin/audit-application/[auditId]/page";
import { PageHeaderHarness } from "@/test/pageHeaderHarness";

/* Renders the page's registered `.top` actions like AdminShell does. */
const renderPage = () =>
  render(
    <PageHeaderHarness>
      <AdminAuditDetailPage />
    </PageHeaderHarness>
  );

const authState = {
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
};

const adminAccessState = {
  isAdmin: true,
  isLoading: false,
};

const pushMock = vi.fn();

vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    useParams: () => ({ auditId: "42" }),
    useRouter: () => ({ push: pushMock }),
  };
});

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

describe("AdminAuditDetailPage", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
    pushMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders persisted dual-track runtime metadata for the selected audit", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/admin/audits/42?")) {
        return jsonResponse({
          id: 42,
          user_id: 8,
          user_email: "owner@example.com",
          url: "https://brand.example.com",
          audit_target_type: "brand",
          target_name: "Brand Example",
          target_url: "https://brand.example.com",
          geo_score: 82,
          seo_score: 78,
          aeo_score: 84,
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
          subscription_type: "plan_specialist",
          credits_used: 9,
          credits_remaining: 41,
          created_at: "2026-03-11T10:00:00Z",
          sanitized_at: null,
          has_screenshot: false,
          full_report: {
            metadata: {
              grounding_profile: "shadow_dual_track",
              debate: {
                enabled: true,
              },
            },
          },
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    renderPage();

    /*
     * The page lifts its header actions into the shell from an effect, so the
     * debate-trace link lands one commit after the body it describes. Waiting on
     * body text and then querying the link synchronously is a race: React
     * schedules that passive effect on a task while the MutationObserver that
     * resolves `findBy*` runs on a microtask, so under parallel load the body is
     * observable while the header is still empty. The link is the last thing to
     * commit, so waiting for it is the one point that proves the whole screen is
     * settled, and every assertion below can stay synchronous.
     */
    const debateTraceLink = await screen.findByRole("link", { name: /view debate trace/i });

    expect(screen.getByText("Dual-track grounding runtime")).toBeInTheDocument();
    expect(screen.getAllByText("Brand Example").length).toBeGreaterThan(0);
    expect(screen.getByText("shadow dual track")).toBeInTheDocument();
    expect(screen.getByText("Dual-track enabled")).toBeInTheDocument();
    expect(screen.getByText("track b judge unavailable")).toBeInTheDocument();
    expect(screen.getByText("Track A: 3 / Track B: 2")).toBeInTheDocument();
    expect(screen.getByText("allowlist enabled")).toBeInTheDocument();
    expect(debateTraceLink).toHaveAttribute("href", "/admin/audit-application/42/debate-trace");

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(urls).toContain("/api/admin/audits/42?");
    });
  });
});
