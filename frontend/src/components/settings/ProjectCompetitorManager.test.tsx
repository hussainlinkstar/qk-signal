import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectCompetitorManager from "@/components/settings/ProjectCompetitorManager";
import {
  createProjectCompetitor,
  deleteProjectCompetitor,
  fetchProjectById,
  fetchProjectCompetitors,
  updateProjectById,
} from "@/services/workspaceService";

const authState = {
  isLoading: false,
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
  user: {
    subscription_plan: "plan_specialist",
  },
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/services/workspaceService", () => ({
  createProjectCompetitor: vi.fn(),
  deleteProjectCompetitor: vi.fn(),
  fetchProjectById: vi.fn(),
  fetchProjectCompetitors: vi.fn(),
  updateProjectById: vi.fn(),
}));

describe("ProjectCompetitorManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isLoading = false;
    authState.isSignedIn = true;
    authState.user = { subscription_plan: "plan_specialist" };
    authState.getToken = vi.fn(async () => "token-123");

    const featureAccess = {
      monitoring: { allowed: true, detail: null, status_code: null, required_plan: null },
      automations: { allowed: true, detail: null, status_code: null, required_plan: null },
      entity_authority: { allowed: true, detail: null, status_code: null, required_plan: null },
      benchmark_intelligence: {
        allowed: true,
        detail: null,
        status_code: null,
        required_plan: null,
      },
      scheduled_audits: { allowed: true, detail: null, status_code: null, required_plan: null },
      jira_export: { allowed: true, detail: null, status_code: null, required_plan: null },
    };

    vi.mocked(fetchProjectById).mockResolvedValue({
      id: 42,
      workspace_id: 1,
      name: "Northwind",
      domain_url: "https://northwind.example",
      target_country: "US",
      language: "en",
      icp_roles: [],
      pain_points: null,
      usp: null,
      competitors: ["https://contoso.example"],
      priority_pulse_tags: [],
      sme_profiles: [],
      created_at: null,
      audit_count: 0,
      last_audit_at: null,
      latest_seo_score: null,
      latest_geo_score: null,
      latest_aeo_score: null,
      feature_access: featureAccess,
      auto_competitor_audits_enabled: true,
      competitive_digest_frequency: "weekly",
    });
    vi.mocked(fetchProjectCompetitors).mockResolvedValue([
      {
        id: 7,
        project_id: 42,
        competitor_site_id: 88,
        target_url: "https://contoso.example",
        normalized_domain: "contoso.example",
        display_name: "Contoso",
        auto_audit_enabled: true,
        created_at: "2026-03-01T10:00:00.000Z",
        latest_status: "succeeded",
        latest_failure_reason: null,
        last_benchmarked_at: "2026-03-02T08:00:00.000Z",
        latest_source_audit_id: 99,
        latest_scores: {
          geo: 72,
          seo: 78,
          aeo: 69,
          overall: 73,
        },
      },
    ]);
    vi.mocked(updateProjectById).mockResolvedValue({
      id: 42,
      workspace_id: 1,
      name: "Northwind",
      domain_url: "https://northwind.example",
      target_country: "US",
      language: "en",
      icp_roles: [],
      pain_points: null,
      usp: null,
      competitors: ["https://contoso.example"],
      priority_pulse_tags: [],
      sme_profiles: [],
      created_at: null,
      audit_count: 0,
      last_audit_at: null,
      latest_seo_score: null,
      latest_geo_score: null,
      latest_aeo_score: null,
      feature_access: featureAccess,
      auto_competitor_audits_enabled: false,
      competitive_digest_frequency: "monthly",
    });
    vi.mocked(createProjectCompetitor).mockResolvedValue({
      id: 11,
      project_id: 42,
      competitor_site_id: null,
      target_url: "https://fabrikam.example",
      normalized_domain: "fabrikam.example",
      display_name: "Fabrikam",
      auto_audit_enabled: true,
      created_at: "2026-03-02T08:30:00.000Z",
      latest_status: "not_started",
      latest_failure_reason: null,
      last_benchmarked_at: null,
      latest_source_audit_id: null,
      latest_scores: {
        geo: null,
        seo: null,
        aeo: null,
        overall: null,
      },
    });
    vi.mocked(deleteProjectCompetitor).mockResolvedValue();
  });

  it("shows the plan lock on non-eligible tiers", async () => {
    authState.user = { subscription_plan: "plan_standard" };

    render(<ProjectCompetitorManager projectId="42" />);

    expect(
      await screen.findByText(/Competitive Intelligence requires Specialist/i)
    ).toBeInTheDocument();
  });

  it("saves automation preferences and adds a competitor benchmark target", async () => {
    render(<ProjectCompetitorManager projectId="42" />);

    expect(await screen.findByText(/Benchmark Roster/i)).toBeInTheDocument();
    expect(screen.getByText("Contoso")).toBeInTheDocument();

    fireEvent.click(
      screen.getByLabelText(/Auto-run competitor benchmarks after each scheduled audit/i)
    );
    fireEvent.click(screen.getByRole("button", { name: "Monthly" }));
    fireEvent.click(screen.getByRole("button", { name: /Save Automation/i }));

    await waitFor(() => {
      expect(updateProjectById).toHaveBeenCalledWith(
        "42",
        {
          auto_competitor_audits_enabled: false,
          competitive_digest_frequency: "monthly",
        },
        { Authorization: "Bearer token-123" }
      );
    });

    fireEvent.change(screen.getByLabelText(/Competitor Domain/i), {
      target: { value: "https://fabrikam.example" },
    });
    fireEvent.change(screen.getByLabelText(/Label \(optional\)/i), {
      target: { value: "Fabrikam" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add Target/i }));

    await waitFor(() => {
      expect(createProjectCompetitor).toHaveBeenCalledWith(
        "42",
        {
          target_url: "https://fabrikam.example",
          display_name: "Fabrikam",
        },
        { Authorization: "Bearer token-123" }
      );
    });
  });
});
