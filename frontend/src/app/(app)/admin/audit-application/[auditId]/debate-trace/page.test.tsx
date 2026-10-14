import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminDebateTracePage from "@/app/(app)/admin/audit-application/[auditId]/debate-trace/page";

const authState = {
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
};

const adminAccessState = {
  isAdmin: true,
  isLoading: false,
};

vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    useParams: () => ({ auditId: "42" }),
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

describe("AdminDebateTracePage", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the debate timeline, loads agent output, and follows a claim journey", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/admin/audits/42/debate-trace") {
        return jsonResponse({
          audit_id: 42,
          pipeline_type: "delta_flow",
          total_agents: 4,
          total_latency_ms: 8900,
          total_cost_usd: 0.53,
          layers: [
            {
              layer: 1,
              name: "Specialized Generation",
              parallel: true,
              traces: [
                {
                  agent_role: "seo_generator",
                  provider: "google",
                  model: "gemini-2.5-pro",
                  status: "completed",
                  latency_ms: 2100,
                  cost_usd: 0.12,
                  input_chars: 1200,
                  output_preview: "Faceted URLs are wasting crawl budget.",
                  claim_count: 1,
                },
              ],
            },
          ],
        });
      }
      if (url === "/api/admin/audits/42/debate-trace/seo_generator/output") {
        return jsonResponse({
          audit_id: 42,
          agent_role: "seo_generator",
          agent_layer: 1,
          pipeline_type: "delta_flow",
          provider: "google",
          model: "gemini-2.5-pro",
          status: "completed",
          latency_ms: 2100,
          cost_usd: 0.12,
          input_payload_hash: "a".repeat(64),
          input_payload_chars: 1200,
          input_payload: { system_prompt: "SEO prompt", user_prompt: ["seo-01"] },
          output_raw: {
            claim_ledger: [
              {
                claim_id: "seo-01",
                claim_text: "Faceted URLs are wasting crawl budget.",
              },
            ],
          },
          output_claim_ledger: {
            claim_ledger: [
              {
                claim_id: "seo-01",
                claim_text: "Faceted URLs are wasting crawl budget.",
              },
            ],
          },
          created_at: "2026-03-16T10:00:00Z",
        });
      }
      if (url === "/api/admin/audits/42/debate-trace/claim/seo-01/journey") {
        return jsonResponse({
          audit_id: 42,
          claim_id: "seo-01",
          claim_text: "Faceted URLs are wasting crawl budget.",
          claim_domain: "seo",
          journey: [
            {
              layer: 1,
              agent: "seo_generator",
              provider: "google",
              model: "gemini-2.5-pro",
              status: "completed",
              action: "generated",
              confidence: 0.91,
            },
            {
              layer: 2,
              agent: "seo_critic",
              provider: "openai",
              model: "gpt-5",
              status: "completed",
              action: "challenged",
              critique: "The crawl sample is narrow.",
              suggested_disposition: "downgrade",
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AdminDebateTracePage />);

    /*
     * The page title comes from `useParams`, so it is on screen in the very
     * first commit, before the timeline fetch has even been issued. Waiting on
     * it and then querying the timeline synchronously asserts that the fetch
     * resolved inside React's own act flush, which is a race: under parallel
     * load that flush can end before the response body is read, and the layer
     * name is then missing. Each value waits for its own commit instead.
     */
    expect(await screen.findByText("Audit #42 debate trace")).toBeInTheDocument();
    expect(await screen.findByText("Specialized Generation")).toBeInTheDocument();
    expect(await screen.findByText("Faceted URLs are wasting crawl budget.")).toBeInTheDocument();
    expect(await screen.findByText(/seo prompt/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Claim ID"), { target: { value: "seo-01" } });
    fireEvent.click(screen.getByRole("button", { name: /load journey/i }));

    expect(await screen.findByText("Faceted URLs are wasting crawl budget.")).toBeInTheDocument();
    expect(
      await screen.findByText(/critique:\s*the crawl sample is narrow\./i)
    ).toBeInTheDocument();

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(urls).toContain("/api/admin/audits/42/debate-trace");
      expect(urls).toContain("/api/admin/audits/42/debate-trace/seo_generator/output");
      expect(urls).toContain("/api/admin/audits/42/debate-trace/claim/seo-01/journey");
    });
  });
});
