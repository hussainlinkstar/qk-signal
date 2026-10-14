import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardAuditHistory } from "@/hooks/useDashboardAuditHistory";

const authState = {
  isSignedIn: true,
  getToken: vi.fn(async () => "token"),
};

const searchParamsState = {
  get: vi.fn(() => null as string | null),
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParamsState,
}));

const tMock = vi.fn((key: string) => key) as any;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: tMock,
  }),
}));

const buildAuditResult = () => ({
  schema_version: "1",
  site: { url: "https://example.com", market: "global", language: "en" },
  seo: { onpage: 75, performance: 70, indexing: 80 },
  geo: { visibility_index: 60, citation_share: 50, brand_anchor: 55 },
  aeo: { answerability_score: 65, extractable_pages: 4 },
  entities: [],
  competitors: [],
  suggestions: [],
  scores: { seo: 75, geo: 60, aeo: 65 },
  metadata: {
    created_at: "2025-01-01T00:00:00.000Z",
    updated_at: "2025-01-01T00:00:00.000Z",
    plan: "plan_standard",
    version: "1",
    audit_outcome: "completed",
  },
});

describe("useDashboardAuditHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParamsState.get.mockReturnValue(null);

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.startsWith("/api/workspaces/current/projects")) {
          return {
            ok: true,
            json: async () => [
              {
                id: 1,
                workspace_id: 1,
                name: "Example",
                domain_url: "https://example.com",
                target_country: "RO",
                language: "en",
                icp_roles: [],
                pain_points: null,
                usp: null,
                competitors: [],
                priority_pulse_tags: [],
                sme_profiles: [],
                created_at: "2026-01-01T00:00:00Z",
                audit_count: 0,
                last_audit_at: null,
                latest_geo_score: null,
                latest_aeo_score: null,
                latest_seo_score: null,
              },
            ],
          } as Response;
        }

        if (url.startsWith("/api/projects/1/audits")) {
          return {
            ok: true,
            json: async () => [],
          } as Response;
        }

        throw new Error(`Unexpected fetch URL: ${url}`);
      })
    );
  });

  it("fetches project-scoped history when no projectId is present", async () => {
    const { result } = renderHook(() => useDashboardAuditHistory());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(global.fetch).toHaveBeenCalledWith("/api/workspaces/current/projects", {
      method: "GET",
      headers: { Authorization: "Bearer token" },
      body: undefined,
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/1/audits?limit=25&include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
  });

  it("fetches selected project history when projectId is valid", async () => {
    searchParamsState.get.mockImplementation(((key: string) =>
      key === "projectId" ? "42" : null) as any);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.startsWith("/api/projects/42/audits")) {
          return {
            ok: true,
            json: async () => [],
          } as Response;
        }

        if (url.startsWith("/api/workspaces/current/projects")) {
          return {
            ok: true,
            json: async () => [],
          } as Response;
        }

        throw new Error(`Unexpected fetch URL: ${url}`);
      })
    );

    const { result } = renderHook(() => useDashboardAuditHistory());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/42/audits?limit=100&include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
  });

  it("marks hasCompletedAudit=true when project audit payload includes full_report", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.startsWith("/api/workspaces/current/projects")) {
          return {
            ok: true,
            json: async () => [
              {
                id: 1,
                workspace_id: 1,
                name: "Example",
                domain_url: "https://example.com",
                target_country: "RO",
                language: "en",
                icp_roles: [],
                pain_points: null,
                usp: null,
                competitors: [],
                priority_pulse_tags: [],
                sme_profiles: [],
                created_at: "2026-01-01T00:00:00Z",
                audit_count: 1,
                last_audit_at: "2026-01-02T00:00:00Z",
                latest_geo_score: 65,
                latest_aeo_score: 62,
                latest_seo_score: 70,
              },
            ],
          } as Response;
        }

        if (url.startsWith("/api/projects/1/audits")) {
          return {
            ok: true,
            json: async () => [
              {
                id: 10,
                project_id: 1,
                audit_type: "DEEP",
                url: "https://example.com",
                geo_score: 65,
                seo_score: 70,
                aeo_score: 62,
                status: "completed",
                created_at: "2026-01-02T00:00:00Z",
                full_report: buildAuditResult(),
              },
            ],
          } as Response;
        }

        throw new Error(`Unexpected fetch URL: ${url}`);
      })
    );

    const { result } = renderHook(() => useDashboardAuditHistory());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.hasCompletedAudit).toBe(true);
    expect(result.current.history).toHaveLength(1);
  });
});
