import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminPaymentSettingsPage from "@/app/(app)/admin/settings/payments/page";

/* ── Mocks ──────────────────────────────────────────────────────── */

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

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn(), loading: vi.fn() },
}));

/* ── Fixture helpers ────────────────────────────────────────────── */

const buildConfig = (overrides?: Partial<Record<string, unknown>>) => ({
  billing_enabled: true,
  webhook_configured: true,
  stripe_mode: "test",
  stripe_mode_source: "env",
  has_runtime_override: false,
  modes: [
    {
      mode: "test",
      secret_configured: true,
      webhook_configured: true,
      secret_hint: "****1234",
      webhook_hint: "****9876",
    },
    {
      mode: "live",
      secret_configured: true,
      webhook_configured: true,
      secret_hint: "****5678",
      webhook_hint: "****4321",
    },
  ],
  price_ids: [
    {
      plan: "plan_standard",
      configured: true,
      active_price_id: "price_test_plan_standard",
      test_price_id: "price_test_plan_standard",
      live_price_id: "price_live_plan_standard",
    },
    {
      plan: "plan_specialist",
      configured: true,
      active_price_id: "price_test_plan_specialist",
      test_price_id: "price_test_plan_specialist",
      live_price_id: "price_live_plan_specialist",
    },
    {
      plan: "plan_executive",
      configured: true,
      active_price_id: "price_test_plan_executive",
      test_price_id: "price_test_plan_executive",
      live_price_id: "price_live_plan_executive",
    },
  ],
  commitment_price_ids: [
    {
      tier: "growth",
      configured: true,
      active_price_id: "price_test_growth",
      test_price_id: "price_test_growth",
      live_price_id: "price_live_growth",
    },
    {
      tier: "scale",
      configured: true,
      active_price_id: "price_test_scale",
      test_price_id: "price_test_scale",
      live_price_id: "price_live_scale",
    },
    {
      tier: "enterprise",
      configured: true,
      active_price_id: "price_test_enterprise",
      test_price_id: "price_test_enterprise",
      live_price_id: "price_live_enterprise",
    },
  ],
  commitment_overage_price_ids: {
    configured: true,
    active_price_id: "price_test_overage",
    test_price_id: "price_test_overage",
    live_price_id: "price_live_overage",
  },
  ...overrides,
});

const buildOverview = (overrides?: Partial<Record<string, unknown>>) => ({
  stripe_mode: "test",
  billing_enabled: true,
  stripe_connected: true,
  stripe_error: null,
  total_subscriptions: 12,
  active_subscriptions: 10,
  total_invoices: 33,
  paid_invoices: 30,
  open_invoices: 3,
  monthly_recurring_revenue_estimate: 12345,
  latest_invoice_at: "2026-03-07T09:00:00Z",
  ...overrides,
});

const jsonResponse = (payload: unknown) =>
  new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

/* ── Tests ──────────────────────────────────────────────────────── */

describe("AdminPaymentSettingsPage", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders all four canonical billing plans on the Pricing tab", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/admin/billing/config") return jsonResponse(buildConfig());
      if (url === "/api/admin/billing/overview") return jsonResponse(buildOverview());
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AdminPaymentSettingsPage />);

    await screen.findByText("Runtime controls");

    fireEvent.click(screen.getByRole("tab", { name: /pricing/i }));

    await waitFor(() => {
      expect(screen.getByText("Standard")).toBeInTheDocument();
      expect(screen.getByText("Specialist")).toBeInTheDocument();
      expect(screen.getByText("Executive")).toBeInTheDocument();
    });
  });

  it("posts the requested sync scope, mode, and dry-run flag", async () => {
    let syncBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/admin/billing/config") return jsonResponse(buildConfig());
      if (url === "/api/admin/billing/overview") return jsonResponse(buildOverview());
      if (url === "/api/admin/billing/catalog/sync") {
        syncBody = JSON.parse(String(init?.body ?? "{}"));
        return jsonResponse({
          mode: "live",
          scope: "commitments",
          dry_run: true,
          result: {
            items: [],
            plan_price_ids: {},
            commitment_price_ids: {},
            commitment_overage_price_id: null,
            warnings: [],
          },
          config: buildConfig(),
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AdminPaymentSettingsPage />);

    await screen.findByText("Runtime controls");

    fireEvent.click(screen.getByRole("tab", { name: /catalog/i }));

    await waitFor(() => {
      expect(screen.getByText("Stripe catalog")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Catalog mode"), { target: { value: "live" } });
    fireEvent.click(screen.getByRole("switch", { name: /dry run/i }));
    fireEvent.click(screen.getByRole("button", { name: /sync commitments/i }));

    await waitFor(() => {
      expect(syncBody).toEqual({
        mode: "live",
        scope: "commitments",
        dry_run: true,
      });
    });
  });

  it("rehydrates the form from the returned config after a non-dry-run sync", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/admin/billing/config") return jsonResponse(buildConfig());
      if (url === "/api/admin/billing/overview") return jsonResponse(buildOverview());
      if (url === "/api/admin/billing/catalog/sync") {
        return jsonResponse({
          mode: "live",
          scope: "plans",
          dry_run: false,
          result: {
            items: [
              {
                kind: "plan",
                key: "plan_executive",
                product_id: "prod_live_plan_executive",
                price_id: "price_live_plan_executive_synced",
                action: "created",
                message: "Created managed product and price.",
              },
            ],
            plan_price_ids: {
              plan_executive: "price_live_plan_executive_synced",
            },
            commitment_price_ids: {},
            commitment_overage_price_id: null,
            warnings: [],
          },
          config: buildConfig({
            price_ids: [
              ...buildConfig().price_ids.slice(0, 2),
              {
                plan: "plan_executive",
                configured: true,
                active_price_id: "price_live_plan_executive_synced",
                test_price_id: "",
                live_price_id: "price_live_plan_executive_synced",
              },
            ],
          }),
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AdminPaymentSettingsPage />);

    await screen.findByText("Runtime controls");

    fireEvent.click(screen.getByRole("tab", { name: /catalog/i }));

    await waitFor(() => {
      expect(screen.getByText("Stripe catalog")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Catalog mode"), { target: { value: "live" } });
    fireEvent.click(screen.getByRole("button", { name: /sync plans/i }));

    await waitFor(() => {
      expect(screen.getByText("created")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("tab", { name: /pricing/i }));

    await waitFor(() => {
      expect(screen.getByDisplayValue("price_live_plan_executive_synced")).toBeInTheDocument();
    });
  });

  it("renders validation statuses for valid, missing, and mismatch results", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/admin/billing/config") return jsonResponse(buildConfig());
      if (url === "/api/admin/billing/overview") return jsonResponse(buildOverview());
      if (url === "/api/admin/billing/catalog/validate") {
        expect(JSON.parse(String(init?.body ?? "{}"))).toEqual({
          mode: "test",
          scope: "all",
        });
        return jsonResponse({
          mode: "test",
          scope: "all",
          results: [
            {
              kind: "plan",
              key: "plan_standard",
              configured_price_id: "price_test_plan_standard",
              status: "valid",
              message: "Configured Stripe price matches the canonical catalog definition.",
              expected: {},
              actual: {},
            },
            {
              kind: "plan",
              key: "plan_executive",
              configured_price_id: "price_missing_plan_executive",
              status: "missing",
              message: "Configured Stripe price was not found.",
              expected: {},
              actual: {},
            },
            {
              kind: "commitment_overage",
              key: "shared",
              configured_price_id: "price_test_overage",
              status: "mismatch",
              message: "Configured Stripe price does not match the canonical catalog definition.",
              expected: {},
              actual: {},
            },
          ],
          config: buildConfig(),
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    render(<AdminPaymentSettingsPage />);

    await screen.findByText("Runtime controls");

    fireEvent.click(screen.getByRole("tab", { name: /catalog/i }));

    await waitFor(() => {
      expect(screen.getByText("Stripe catalog")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /validate catalog/i }));

    await waitFor(() => {
      expect(screen.getByText("Validation results")).toBeInTheDocument();
      expect(screen.getByText("valid")).toBeInTheDocument();
      expect(screen.getByText("missing")).toBeInTheDocument();
      expect(screen.getByText("mismatch")).toBeInTheDocument();
    });
  });
});
