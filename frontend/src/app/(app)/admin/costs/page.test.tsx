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
    BarChart: svgContainer,
    Bar: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Cell: () => null,
  };
});

import AdminCostsDashboard from "@/app/(app)/admin/costs/page";

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

describe("AdminCostsDashboard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("propagates requested tier and debate profile filters to every cost endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/admin/costs/summary")) {
        return jsonResponse({
          currency: "USD",
          fx_reference: {
            usd_per_usd: 1.1,
            eur_per_usd: 0.90909091,
            effective_date: "2026-03-12",
            source: "ecb_reference",
            status: "ok",
          },
          current_month_cost: 7.5,
          projected_month_end: 20.0,
          avg_cost_per_audit: 7.5,
          total_tokens_month: 3000,
          audit_count_month: 1,
          prev_month_audit_count: 0,
          top_model: "gpt-5",
          top_model_cost: 7.5,
        });
      }
      if (url.startsWith("/api/admin/costs/daily")) {
        return jsonResponse({
          days: 30,
          series: [],
          summary: { total_cost: 7.5, avg_daily: 0.25 },
        });
      }
      if (url.startsWith("/api/admin/costs/by-model")) {
        return jsonResponse({ window_days: 30, models: [], total_cost: 7.5 });
      }
      if (url.startsWith("/api/admin/costs/by-workspace")) {
        return jsonResponse({ window_days: 30, workspaces: [] });
      }
      if (url.startsWith("/api/admin/costs/by-user")) {
        return jsonResponse({ window_days: 30, users: [] });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(
      <div style={{ width: 1280, minHeight: 1200 }}>
        <AdminCostsDashboard />
      </div>
    );

    await screen.findByLabelText("Requested tier");
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(5);
    });

    fetchMock.mockClear();

    fireEvent.change(screen.getByLabelText("Requested tier"), {
      target: { value: "deep_judgment" },
    });

    await screen.findByLabelText("Debate profile");

    fireEvent.change(screen.getByLabelText("Debate profile"), {
      target: { value: "high_confidence" },
    });

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(urls).toContain(
        "/api/admin/costs/summary?requested_tier=deep_judgment&debate_profile=high_confidence"
      );
      expect(urls).toContain(
        "/api/admin/costs/daily?days=30&requested_tier=deep_judgment&debate_profile=high_confidence"
      );
      expect(urls).toContain(
        "/api/admin/costs/by-model?window_days=30&requested_tier=deep_judgment&debate_profile=high_confidence"
      );
      expect(urls).toContain(
        "/api/admin/costs/by-workspace?window_days=30&limit=10&requested_tier=deep_judgment&debate_profile=high_confidence"
      );
      expect(urls).toContain(
        "/api/admin/costs/by-user?window_days=30&limit=10&requested_tier=deep_judgment&debate_profile=high_confidence"
      );
    });

    // The caption is "Filtered to <tier> - <profile>" in one paragraph, so the
    // tier label and separator sit between the two words this used to match.
    expect(screen.getByText(/filtered to .*high confidence/i)).toBeInTheDocument();
  });

  it("renders USD AI spend labels", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/admin/costs/summary")) {
        return jsonResponse({
          currency: "USD",
          currency_policy: {
            canonical_cost_currency: "USD",
            billing_catalog_currency: "EUR",
            reporting_display_currency: "USD",
            manual_usd_per_usd: null,
            rate_source: "ecb_reference",
            fx_effective_date: "2026-03-12",
            usd_per_usd: 1.1,
            eur_per_usd: 0.90909091,
            status: "ok",
          },
          fx_reference: {
            usd_per_usd: 1.1,
            eur_per_usd: 0.90909091,
            effective_date: "2026-03-12",
            source: "ecb_reference",
            status: "ok",
          },
          current_month_cost: 7.5,
          projected_month_end: 20.0,
          avg_cost_per_audit: 7.5,
          total_tokens_month: 3000,
          audit_count_month: 1,
          prev_month_audit_count: 0,
          top_model: "gpt-5",
          top_model_cost: 7.5,
        });
      }
      if (url.startsWith("/api/admin/costs/daily")) {
        return jsonResponse({
          currency: "USD",
          series: [
            {
              date: "2026-03-10",
              total_cost: 7.5,
              total_tokens: 3000,
              audit_count: 1,
              by_model: {},
            },
          ],
          summary: { total_cost: 7.5, avg_daily: 7.5 },
        });
      }
      if (url.startsWith("/api/admin/costs/by-model")) {
        return jsonResponse({
          currency: "USD",
          window_days: 30,
          models: [
            {
              model: "gpt-5",
              tokens: 3000,
              cost: 7.5,
              audits: 1,
              cost_per_1m_usd: { input: 1.25, output: 10 },
            },
          ],
          total_cost: 7.5,
        });
      }
      if (url.startsWith("/api/admin/costs/by-workspace")) {
        return jsonResponse({
          currency: "USD",
          window_days: 30,
          workspaces: [
            {
              workspace_id: 1,
              workspace_name: "Acme Workspace",
              cost: 7.5,
              audits: 1,
              tokens: 3000,
            },
          ],
        });
      }
      if (url.startsWith("/api/admin/costs/by-user")) {
        return jsonResponse({
          currency: "USD",
          window_days: 30,
          users: [{ user_id: 1, email: "admin@acme.test", cost: 7.5, audits: 1, tokens: 3000 }],
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(
      <div style={{ width: 1280, minHeight: 1200 }}>
        <AdminCostsDashboard />
      </div>
    );

    expect(await screen.findByText(/AI spend tracked in USD\./i)).toBeInTheDocument();
    expect(screen.getAllByText("$7.50").length).toBeGreaterThan(0);
    expect(screen.getByText("$20.00")).toBeInTheDocument();
    expect(screen.getByText("$7.50 this month")).toBeInTheDocument();
    expect(screen.getByText(/Top workspaces by cost/)).toBeInTheDocument();
    expect(screen.getByText(/Top users by AI cost/)).toBeInTheDocument();
    expect(screen.queryByText("€7.50")).not.toBeInTheDocument();
  });
});
