import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuditPromptsSection from "@/components/results/AuditPromptsSection";
import type { ScanPromptsState } from "@/hooks/useScanPrompts";
import { tEn } from "@/test/i18nEn";
import type { VisibilityEntitlements, VisibilityQuery } from "@/types/monitoring";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("@/services/monitoringService", () => ({
  createVisibilityQuery: vi.fn(),
  updateVisibilityQuery: vi.fn(),
  deleteVisibilityQuery: vi.fn(),
  generateBaseVisibilityPrompts: vi.fn(),
}));

vi.mock("@/components/signal/SignalAddPromptModal", () => ({
  default: () => null,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const entitlements: VisibilityEntitlements = {
  plan: "plan_standard",
  plan_label: "Standard",
  upgrade_plan: "plan_specialist",
  upgrade_plan_label: "Specialist",
  upgrade_max_queries: 50,
  max_queries: 10,
  used_queries: 1,
  remaining_queries: 9,
  allowed_providers: ["openai"],
  is_locked: false,
  estimated_cost_per_check: {},
};

const prompt = (id: number, text: string): VisibilityQuery => ({
  id,
  project_id: 42,
  query_text: text,
  query_type: "aeo",
  providers: ["openai"],
  is_active: true,
  created_at: null,
  updated_at: null,
});

const state = (overrides: Partial<ScanPromptsState> = {}): ScanPromptsState => ({
  projectId: 42,
  prompts: [prompt(1, "best boutique hotels near the harbour")],
  coverage: [],
  entitlements,
  project: null,
  isLoading: false,
  error: null,
  canAddPrompt: true,
  isPlanLocked: false,
  hasPrompt: true,
  blocksLaunch: false,
  reload: vi.fn().mockResolvedValue(undefined),
  ...overrides,
});

const getAuthHeaders = vi.fn().mockResolvedValue({ Authorization: "Bearer token" });

/**
 * The section is the scan-mode host of the approved prompt-setup surface
 * (SIGV2-1194). The surface itself is covered in PromptSetup.test.tsx; what
 * stays here are the states where there is no list to show, each stated as
 * what it is rather than as a refusal, because only "no prompts at all"
 * blocks a launch.
 */
describe("AuditPromptsSection (SIGV2-1194)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the approved prompt-setup surface in scan mode", () => {
    render(<AuditPromptsSection prompts={state()} getAuthHeaders={getAuthHeaders} />);

    expect(screen.getByText("Prompts for this scan")).toBeInTheDocument();
    expect(screen.getByText("best boutique hotels near the harbour")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage all prompts" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/ai-answers?tab=prompts"
    );
  });

  it("explains itself rather than refusing when there is no project yet", () => {
    render(
      <AuditPromptsSection
        prompts={state({ projectId: null, prompts: [], hasPrompt: false, entitlements: null })}
        getAuthHeaders={getAuthHeaders}
      />
    );

    // SIGV2-1287: it states what it knows, which is that it has no project id.
    // It used to assert "this scan has no project yet", a claim about the
    // user's data, and the scan form could reach that state with a project
    // that had prompts in it, simply by losing the query parameter.
    expect(screen.getByRole("status")).toHaveTextContent("Pick a project to see the prompts");
    expect(screen.getByRole("status")).not.toHaveTextContent("has no project yet");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Prompts for this scan")).toBeNull();
  });

  it("says the list could not be read, instead of claiming there are none", () => {
    render(
      <AuditPromptsSection
        prompts={state({ prompts: [], hasPrompt: false, error: "monitoring is unreachable" })}
        getAuthHeaders={getAuthHeaders}
      />
    );

    expect(
      screen.getByText(
        "This project's prompt list could not be read, so the scan is not held up. Check the Prompts section after the run."
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names the plan when the plan tracks no prompts at all", () => {
    render(
      <AuditPromptsSection
        prompts={state({
          prompts: [],
          hasPrompt: false,
          isPlanLocked: true,
          canAddPrompt: false,
          entitlements: { ...entitlements, is_locked: true, max_queries: 0, used_queries: 0 },
        })}
        getAuthHeaders={getAuthHeaders}
      />
    );

    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.getByText(
        "AI visibility monitoring is not included in the Standard plan, so prompts cannot be tracked yet."
      )
    ).toBeInTheDocument();
  });

  it("states the mandatory-prompt refusal, and only it, when the list is empty", () => {
    render(
      <AuditPromptsSection
        prompts={state({ prompts: [], hasPrompt: false, blocksLaunch: true })}
        getAuthHeaders={getAuthHeaders}
      />
    );

    const refusal = screen.getByText(/Add at least one prompt before you start the scan/);
    expect(refusal.closest("[data-signal-inline-note]")).toHaveAttribute(
      "data-signal-inline-note",
      "danger"
    );
    // Zero prompts is a refusal, not a coverage report: no gap note alongside.
    expect(screen.queryByText(/an untested type has no score/)).toBeNull();
  });
});
