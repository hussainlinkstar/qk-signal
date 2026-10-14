import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => {
  const svgContainer = ({ children }: { children?: React.ReactNode }) => <svg>{children}</svg>;
  const responsiveContainer = ({ children }: { children?: React.ReactNode }) => (
    <div style={{ width: 960, height: 320 }}>{children}</div>
  );
  return {
    ResponsiveContainer: responsiveContainer,
    AreaChart: svgContainer,
    Area: () => null,
    LineChart: svgContainer,
    Line: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
  };
});

import AdminObservabilityPage from "@/app/(app)/admin/observability/page";

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

describe("AdminObservabilityPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders dual-track rollout state and shadow counters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/v1/admin/observability/metrics")) {
        return jsonResponse([
          {
            id: 1,
            snapshot_at: "2026-03-11T09:00:00Z",
            requests_total: 100,
            requests_2xx: 95,
            requests_4xx: 3,
            requests_5xx: 2,
            latency_avg_ms: 245,
            audit_jobs_completed: 12,
            audit_jobs_failed: 1,
            slow_endpoints: {
              "GET /api/v1/audit": 875,
            },
          },
          {
            id: 2,
            snapshot_at: "2026-03-11T10:00:00Z",
            requests_total: 180,
            requests_2xx: 170,
            requests_4xx: 6,
            requests_5xx: 4,
            latency_avg_ms: 260,
            audit_jobs_completed: 20,
            audit_jobs_failed: 1,
            slow_endpoints: {
              "GET /api/v1/audit": 920,
            },
          },
        ]);
      }
      if (url.startsWith("/api/v1/admin/observability/slow-endpoints")) {
        return jsonResponse({
          "GET /api/v1/audit": 920,
        });
      }
      if (url.startsWith("/api/v1/admin/observability/uptime")) {
        return jsonResponse({
          uptime_percentage: 99.5,
          total_downtime_minutes: 15,
        });
      }
      if (url === "/api/v1/admin/observability/dual-track-grounding") {
        return jsonResponse({
          description:
            "Dual-track grounding runs automatically for deep_judgment audits. Lower tiers remain single-track.",
          mode: "canonical_deep_judgment",
          effective_scope: "deep_judgment_only",
          source: "canonical",
          metrics: {
            claims_observed: 8,
            reason_codes_observed: 3,
            fallbacks_observed: 1,
            claim_dispositions: {
              track_a: { supported: 3 },
              track_b: { blocked: 2, rewrite_required: 3 },
            },
            reason_codes: {
              track_b: {
                unsupported_premise_ref: 2,
                missing_citation: 1,
              },
            },
            fallback_reasons: {
              track_b_judge_unavailable: 1,
            },
            top_reason_codes: [
              {
                track: "track_b",
                reason_code: "unsupported_premise_ref",
                count: 2,
              },
            ],
          },
        });
      }
      if (url.startsWith("/api/v1/admin/observability/prompt-quality-gate")) {
        return jsonResponse({
          schema_version: "orchestra-v3-qg-1",
          window_days: 7,
          audits_checked: 4,
          audits_failed: 1,
          failure_rate: 0.25,
          thresholds: {
            generator_grounding_rate_min: 0.85,
            generator_domain_boundary_violations_max: 0,
            generator_anchor_contradiction_rate_max: 0.1,
            magistrate_needs_manual_review_rate_max: 0.25,
            magistrate_needs_manual_review_rate_min: 0.03,
          },
          top_violations: [
            {
              code: "magistrate_over_flagging",
              count: 2,
            },
          ],
          tier_summary: {
            deep_judgment: {
              audits_checked: 2,
              audits_failed: 1,
              violation_count: 2,
              failure_rate: 0.5,
            },
          },
          recent_failures: [
            {
              audit_id: 4523,
              created_at: "2026-03-16T10:30:00Z",
              requested_tier: "deep_judgment",
              pipeline_type: "delta_flow",
              violation_codes: ["magistrate_over_flagging"],
            },
          ],
          comparison: {
            previous_window: {
              window_days: 7,
              audits_checked: 3,
              audits_failed: 0,
              failure_rate: 0,
            },
            deltas: {
              audits_checked: 1,
              audits_failed: 1,
              failure_rate: 0.25,
            },
          },
        });
      }
      if (url.startsWith("/api/v1/admin/observability/prompt-quality-calibration")) {
        return jsonResponse({
          schema_version: "orchestra-v3-calibration-report-1",
          summary: {
            audits_considered: 4,
            audits_with_quality_gate: 4,
            audits_failed: 1,
            failure_rate: 0.25,
            audits_with_traces: 3,
            calibration_ready_audits: 3,
            calibration_ready_failures: 1,
          },
          audits: [
            {
              audit_id: 4523,
              requested_tier: "deep_judgment",
              pipeline_type: "delta_flow",
              quality_gate_passed: false,
              trace_count: 8,
              calibration_ready: true,
              missing_artifacts: [],
              suggested_prompt_files: ["backend/prompts/deep_judgment/global_magistrate.md"],
              violation_codes: ["magistrate_over_flagging"],
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AdminObservabilityPage />);

    /*
     * The page loads its three optional panels with three sequential awaits, so
     * dual-track, quality gate and calibration land in three separate commits.
     * Waiting on the first and then querying the other two synchronously is a
     * race: under parallel load React's act flush can end between them. The
     * calibration panel is the last to mount, so waiting for it proves all
     * three have landed and every assertion below can stay synchronous.
     */
    expect(await screen.findByText("Prompt calibration workflow")).toBeInTheDocument();
    expect(screen.getByText("Dual-track grounding runtime")).toBeInTheDocument();
    expect(screen.getByText("deep_judgment_only")).toBeInTheDocument();
    expect(screen.getByText("Canonical Deep Judgment")).toBeInTheDocument();
    expect(
      screen.getByText("Source: Canonical runtime. No rollout gating remains.")
    ).toBeInTheDocument();
    expect(screen.getByText("unsupported_premise_ref")).toBeInTheDocument();
    expect(screen.getByText("track_b_judge_unavailable")).toBeInTheDocument();
    expect(screen.getByText("Orchestra prompt quality gate")).toBeInTheDocument();
    expect(screen.getByText("Calibration-ready failures")).toBeInTheDocument();
    expect(
      screen.getByText(/Current 7-day failure rate: 25% vs previous window: 0%/i)
    ).toBeInTheDocument();
    expect(screen.getByText("Failure rate delta: +25 pts")).toBeInTheDocument();
    expect(screen.getAllByText("magistrate_over_flagging")).toHaveLength(3);
    expect(screen.getAllByText(/Audit #4523/i)).toHaveLength(2);
    expect(
      screen.getByText("backend/prompts/deep_judgment/global_magistrate.md")
    ).toBeInTheDocument();

    // The tier filter is labelled from TIER_SHORT, where deep_judgment is "Deep".
    fireEvent.click(screen.getByRole("button", { name: "Deep" }));

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(urls).toContain("/api/v1/admin/observability/dual-track-grounding");
      expect(urls).toContain("/api/v1/admin/observability/prompt-quality-gate?days=7");
      expect(urls).toContain("/api/v1/admin/observability/prompt-quality-calibration?days=7");
      expect(urls).toContain(
        "/api/v1/admin/observability/prompt-quality-gate?days=7&tier=deep_judgment"
      );
      expect(urls).toContain(
        "/api/v1/admin/observability/prompt-quality-calibration?days=7&tier=deep_judgment"
      );
    });
  });
});
