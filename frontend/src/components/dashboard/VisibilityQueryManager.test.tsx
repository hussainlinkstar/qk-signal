import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import VisibilityQueryManager from "@/components/dashboard/VisibilityQueryManager";
import { tEn } from "@/test/i18nEn";
import type { VisibilityEntitlements, VisibilityQuery } from "@/types/monitoring";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const entitlementsFixture: VisibilityEntitlements = {
  plan: "plan_standard",
  plan_label: "Standard",
  upgrade_plan: "plan_specialist",
  upgrade_plan_label: "Specialist",
  upgrade_max_queries: 50,
  max_queries: 10,
  used_queries: 10,
  remaining_queries: 0,
  allowed_providers: ["google"],
  is_locked: false,
  estimated_cost_per_check: {
    google: 1,
  },
};

const queriesFixture: VisibilityQuery[] = [
  {
    id: 1,
    project_id: 42,
    query_text: "best payroll software",
    query_type: "aeo",
    search_type: "category",
    search_type_source: "stored",
    search_type_suggested: "category",
    origin: "customer",
    is_generated: false,
    providers: ["google"],
    is_active: true,
    created_at: "2026-03-02T10:00:00.000Z",
    updated_at: "2026-03-04T10:00:00.000Z",
  },
];

describe("VisibilityQueryManager", () => {
  // SIGV2-1142: this panel used to carry a second creation form that refused
  // silently at the cap. Creation now lives on the approved AIO Prompts tab,
  // and what is left here states the allowance in full.
  it("states the allowance with what remains and sends creation to the approved tab", () => {
    render(
      <VisibilityQueryManager
        projectId={42}
        queries={queriesFixture}
        entitlements={entitlementsFixture}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getByText("10 of 10 prompts used, 0 remaining")).toBeInTheDocument();
    expect(screen.getByText("Standard")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a prompt" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/ai-answers?tab=prompts"
    );
    expect(screen.queryByRole("button", { name: /Add query/i })).toBeNull();
  });

  // SIGV2-1197: the scored type is shown, attributed to Signal, and never
  // chosen - Jake ruled a customer cannot be expected to pick it from a
  // dropdown. The remedy for a wrong type is rewording on the Prompts tab.
  it("shows the stored search type attributed to Signal, with no choice offered", () => {
    render(
      <VisibilityQueryManager
        projectId={42}
        queries={queriesFixture}
        entitlements={entitlementsFixture}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getByText(/Assigned by Signal/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("says pending classification when a prompt has no resolved type", () => {
    render(
      <VisibilityQueryManager
        projectId={42}
        queries={[{ ...queriesFixture[0], search_type: null, search_type_source: null }]}
        entitlements={entitlementsFixture}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );
    expect(screen.getByText("Pending classification")).toBeInTheDocument();
  });

  it("marks a prompt Signal generated so the customer can tell it from their own", () => {
    render(
      <VisibilityQueryManager
        projectId={42}
        queries={[{ ...queriesFixture[0], origin: "generated", is_generated: true }]}
        entitlements={entitlementsFixture}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );
    expect(screen.getByText("Added by Signal")).toBeInTheDocument();
  });

  it("does not label the customer's own prompt as generated", () => {
    render(
      <VisibilityQueryManager
        projectId={42}
        queries={queriesFixture}
        entitlements={entitlementsFixture}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );
    expect(screen.queryByText("Added by Signal")).toBeNull();
  });
});
