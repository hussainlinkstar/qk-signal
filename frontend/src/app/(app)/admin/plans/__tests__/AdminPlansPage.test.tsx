import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/* -------------------------------------------------------------------------- */
/*  Mocks                                                                     */
/* -------------------------------------------------------------------------- */

// SIGV2-1152: `getToken` has to keep one identity across renders, which is why
// it is declared here and not inside the factory.
//
// The real hook returns `AuthContext`'s `getToken`, which is a
// `useCallback(..., [])`, so it is stable for the life of the provider. The page
// relies on that: `fetchAll` is a `useCallback` over `[getToken]` and the mount
// effect depends on `[fetchAll]`. A factory that returned a fresh arrow on every
// render gave `fetchAll` a new identity on every render, so the effect re-ran on
// every render and each run set `loading` back to true, which rendered again. The
// `act()` inside `fireEvent` flushes that pending effect, which is what turned it
// into a self-sustaining microtask loop: the page remounted thousands of times,
// timers never got a turn, and the jsdom worker had to be killed (493s observed
// on the ticket). Measured here with the old factory: 501 fetch calls after 200
// microtask ticks, 12849 after 5000, with the DOM stuck on the loading spinner.
// With a stable identity it is 3 calls and stays 3.
//
// This is a test-double defect, not a component or jsdom one: no real browser can
// hit it while `AuthContext` keeps `getToken` memoised.
const getToken = () => Promise.resolve("test-token");

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken }),
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/* -------------------------------------------------------------------------- */
/*  Sample data                                                               */
/* -------------------------------------------------------------------------- */

// The matrix keys and the overridable keys are deliberately different sets here,
// mirroring the backend: CAPABILITY_MATRIX feeds capability_keys, while
// OVERRIDABLE_CAPABILITIES (plan_validator.py) feeds overridable_capability_keys.
const MATRIX_ONLY_KEYS = ["max_sites", "max_audits", "api_access"];
const OVERRIDABLE_KEYS = [
  "can_use_slack_integration",
  "can_use_teams_integration",
  "has_advisor_recommendations",
];

const PLANS_RESPONSE = {
  plans: {
    plan_starter: {
      display_name: "Starter",
      monthly_price_usd: 12,
      capabilities: {
        max_sites: 1,
        max_audits: 5,
        api_access: false,
        can_use_slack_integration: false,
        can_use_teams_integration: false,
        has_advisor_recommendations: false,
      },
    },
    plan_standard: {
      display_name: "Standard",
      monthly_price_usd: 99,
      capabilities: {
        max_sites: 1,
        max_audits: 25,
        api_access: false,
        can_use_slack_integration: false,
        can_use_teams_integration: false,
        has_advisor_recommendations: false,
      },
    },
    plan_specialist: {
      display_name: "Specialist",
      monthly_price_usd: 399,
      capabilities: {
        max_sites: 10,
        max_audits: 100,
        api_access: true,
        can_use_slack_integration: true,
        can_use_teams_integration: false,
        has_advisor_recommendations: true,
      },
    },
    plan_executive: {
      display_name: "Executive",
      monthly_price_usd: 999,
      capabilities: {
        max_sites: -1,
        max_audits: 1000,
        api_access: true,
        can_use_slack_integration: true,
        can_use_teams_integration: true,
        has_advisor_recommendations: true,
      },
    },
  },
  capability_keys: [...MATRIX_ONLY_KEYS, ...OVERRIDABLE_KEYS],
  capability_descriptions: {
    max_sites: "Maximum tracked sites",
    max_audits: "Maximum audits per month",
    api_access: "API access",
    can_use_slack_integration: "Slack integration",
    can_use_teams_integration: "Teams integration",
    has_advisor_recommendations: "Advisor recommendations",
  },
  // SIGV2-1147: api_access is plan-gated and the max_* keys are plan-scoped, so
  // an override on any of them would have no effect. Only these three may be
  // granted per workspace.
  overridable_capability_keys: OVERRIDABLE_KEYS,
  override_refusal_reasons: {
    max_sites: "This allowance is read per plan by the audit and site accounting paths.",
    max_audits: "This allowance is read per plan by the audit and site accounting paths.",
    api_access: "This capability is gated per plan rather than per workspace.",
  },
};

const OVERRIDES_RESPONSE = { overrides: [] };

const UNENFORCED_OVERRIDE_RESPONSE = {
  overrides: [
    {
      id: 7,
      workspace_id: 42,
      workspace_name: "Legacy Workspace",
      capability_key: "api_access",
      override_value: true,
      reason: "Negotiated deal",
      created_by_email: "admin@example.test",
      expires_at: null,
      created_at: "2026-03-01T00:00:00",
      is_enforced: false,
      enforcement_reason: "This capability is gated per plan rather than per workspace.",
    },
  ],
};
const FLAGS_RESPONSE = {
  flags: [
    {
      id: 1,
      key: "enable_beta_dashboard",
      description: "Enable the new beta dashboard",
      is_enabled: true,
      rollout_percentage: 50,
      created_at: "2026-03-01T00:00:00",
      updated_at: "2026-03-01T00:00:00",
    },
  ],
};

/* -------------------------------------------------------------------------- */
/*  Import page component                                                     */
/* -------------------------------------------------------------------------- */

import AdminPlansPage from "@/app/(app)/admin/plans/page";

/* -------------------------------------------------------------------------- */
/*  Tests                                                                     */
/* -------------------------------------------------------------------------- */

describe("AdminPlansPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();

    global.fetch = vi.fn((url: string) => {
      if (typeof url === "string" && url.includes("/admin/plans/overrides")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(OVERRIDES_RESPONSE),
        } as Response);
      }
      if (typeof url === "string" && url.includes("/admin/plans")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(PLANS_RESPONSE),
        } as Response);
      }
      if (typeof url === "string" && url.includes("/admin/feature-flags")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(FLAGS_RESPONSE),
        } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    }) as unknown as typeof fetch;
  });

  it("renders the page title", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("Pricing tiers & features")).toBeInTheDocument();
    });
  });

  it("renders plan comparison headers", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("Starter")).toBeInTheDocument();
      expect(screen.getByText("Standard")).toBeInTheDocument();
      expect(screen.getByText("Specialist")).toBeInTheDocument();
      expect(screen.getByText("Executive")).toBeInTheDocument();
    });
  });

  it("renders plan prices in USD", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("$99/mo")).toBeInTheDocument();
      expect(screen.getByText("$399/mo")).toBeInTheDocument();
      expect(screen.getByText("$999/mo")).toBeInTheDocument();
    });
  });

  it("renders capability descriptions as row labels", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("Maximum tracked sites")).toBeInTheDocument();
      expect(screen.getByText("Maximum audits per month")).toBeInTheDocument();
      expect(screen.getByText("API access")).toBeInTheDocument();
    });
  });

  it("shows Unlimited for -1 values", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getAllByText("Unlimited").length).toBeGreaterThan(0);
    });
  });

  it("renders feature flag with toggle", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("enable_beta_dashboard")).toBeInTheDocument();
      expect(screen.getByText("Enable the new beta dashboard")).toBeInTheDocument();
    });
    // Toggle should exist
    const toggle = screen.getByRole("switch", { name: /Toggle enable_beta_dashboard/i });
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("shows empty overrides message", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("No active overrides")).toBeInTheDocument();
    });
  });

  it("shows the New Override button", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("New Override")).toBeInTheDocument();
    });
  });

  it("shows the New Flag button", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByText("New Flag")).toBeInTheDocument();
    });
  });

  /* ---------------------------------------------------------------------- */
  /*  SIGV2-1147 / SIGV2-1152                                               */
  /* ---------------------------------------------------------------------- */
  //
  // These two open the create form, which no test used to do. The hang that
  // blocked them was the test double described at the top of this file, not the
  // form, so the component is unchanged.

  it("offers only the overridable capability keys, not the whole matrix", async () => {
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /New Override/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /New Override/i }));

    const capabilitySelect = screen.getByRole("combobox");
    const offered = within(capabilitySelect)
      .getAllByRole("option")
      .map((option) => option.textContent);

    expect(offered).toEqual(OVERRIDABLE_KEYS);
    for (const planOnlyKey of MATRIX_ONLY_KEYS) {
      expect(offered).not.toContain(planOnlyKey);
    }
    // The matrix itself is wider than the dropdown, so the dropdown is a real
    // restriction rather than an accident of the fixture.
    expect(PLANS_RESPONSE.capability_keys.length).toBeGreaterThan(OVERRIDABLE_KEYS.length);

    expect(capabilitySelect).toHaveValue(OVERRIDABLE_KEYS[0]);
    expect(capabilitySelect).toBeEnabled();
    expect(screen.getByRole("button", { name: /Grant Capability/i })).toBeEnabled();
  });

  it("opens the create form without re-running the page data load", async () => {
    // The loop found in SIGV2-1152 showed up as the mount effect firing again on
    // every render, each run putting the page back into its loading state. Three
    // requests, before and after, is what "the effect ran once" looks like.
    render(<AdminPlansPage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /New Override/i })).toBeInTheDocument();
    });
    expect(global.fetch).toHaveBeenCalledTimes(3);

    fireEvent.click(screen.getByRole("button", { name: /New Override/i }));

    expect(screen.getByRole("button", { name: /Grant Capability/i })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });

  it("labels a stored override that no gate reads as having no effect", async () => {
    global.fetch = vi.fn((url: string) => {
      if (typeof url === "string" && url.includes("/admin/plans/overrides")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(UNENFORCED_OVERRIDE_RESPONSE),
        } as Response);
      }
      if (typeof url === "string" && url.includes("/admin/plans")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(PLANS_RESPONSE),
        } as Response);
      }
      if (typeof url === "string" && url.includes("/admin/feature-flags")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(FLAGS_RESPONSE),
        } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    }) as unknown as typeof fetch;

    render(<AdminPlansPage />);

    await waitFor(() => {
      expect(screen.getByText("Legacy Workspace")).toBeInTheDocument();
    });
    expect(screen.getByText("No effect")).toBeInTheDocument();
    expect(screen.getByText("No effect")).toHaveAttribute(
      "title",
      "This capability is gated per plan rather than per workspace."
    );
  });
});
