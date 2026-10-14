import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SignalAddPromptModal from "@/components/signal/SignalAddPromptModal";
import { tEn } from "@/test/i18nEn";
import type { VisibilityEntitlements } from "@/types/monitoring";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/ui/Modal", () => ({
  default: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div role="dialog">{children}</div> : null,
}));

vi.mock("@/services/monitoringService", () => ({
  createVisibilityQuery: vi.fn(),
}));

const entitlements = (overrides: Partial<VisibilityEntitlements> = {}): VisibilityEntitlements => ({
  plan: "plan_standard",
  plan_label: "Standard",
  upgrade_plan: "plan_specialist",
  upgrade_plan_label: "Specialist",
  upgrade_max_queries: 50,
  max_queries: 10,
  used_queries: 10,
  remaining_queries: 0,
  allowed_providers: ["openai"],
  is_locked: false,
  estimated_cost_per_check: {},
  ...overrides,
});

const renderModal = (e = entitlements()) =>
  render(
    <SignalAddPromptModal
      open
      onClose={vi.fn()}
      projectId="42"
      entitlements={e}
      getAuthHeaders={vi.fn().mockResolvedValue({})}
      onCreated={vi.fn()}
    />
  );

describe("SignalAddPromptModal", () => {
  it("states the cap, the usage and the plan that raises it once the allowance is spent", () => {
    renderModal();

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Prompt limit reached: your Standard plan tracks 10 prompts, 10 are in use and 0 remain."
    );
    expect(dialog).toHaveTextContent(
      "Remove a prompt you no longer track, or upgrade to Specialist to track 50."
    );
    expect(screen.getByRole("button", { name: "Add prompt" })).toBeDisabled();
  });

  // SIGV2-1203: the manage-prompts escape used to land on the project
  // monitoring page, which surrounds the prompts panel with the bot log
  // analyzer and the volatility index. It must go to the Prompts tab.
  it("sends 'Manage prompts' to the Prompts tab, not the monitoring page", () => {
    renderModal();

    expect(screen.getByRole("link", { name: "Manage tracked prompts" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/ai-answers?tab=prompts"
    );
  });
});
