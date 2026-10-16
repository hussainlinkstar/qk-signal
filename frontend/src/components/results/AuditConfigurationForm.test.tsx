import React from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditConfigurationForm from "@/components/results/AuditConfigurationForm";
import type { ScanPromptsState } from "@/hooks/useScanPrompts";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

// Each section is already covered by its own tests; this file is about the
// order they appear in, which is the part of SIGV2-1176 Jake specified
// exactly ("between Context and Entity configuration").
vi.mock("@/components/results/AuditTargetSection", () => ({
  default: () => <section id="audit-step-target" />,
}));
vi.mock("@/components/results/AuditContextSection", () => ({
  default: () => <section id="audit-step-context" />,
}));
vi.mock("@/components/results/AuditPromptsSection", () => ({
  default: () => <section id="audit-step-prompts" />,
}));
vi.mock("@/components/results/AuditEntitiesSection", () => ({
  default: () => <section id="audit-step-entities" />,
}));
vi.mock("@/components/results/AuditAllowanceSection", () => ({
  default: () => <section id="audit-step-allowance" />,
}));
vi.mock("@/components/results/AuditDepthSection", () => ({
  default: () => <section id="audit-step-depth" />,
}));
vi.mock("@/components/results/AuditLaunchSection", () => ({
  default: () => <section id="audit-step-launch" />,
}));
vi.mock("@/components/results/AuditStickyStartBar", () => ({
  default: () => null,
}));

const auditForm = {
  form: {
    provider: "google",
    tier: "fast",
    url: "https://northwind.example",
    targetUrl: "https://northwind.example",
    targetName: "Northwind",
  },
  entitySummary: null,
};

const auditRunner = {
  runPhase: "idle",
  runSnapshot: null,
  completedAuditMeta: null,
  handleSubmit: vi.fn(),
  dismissRun: vi.fn(),
  scansUsed: null,
  scansRemaining: null,
  scansResetAt: null,
};

const prompts = {
  projectId: 42,
  prompts: [],
  entitlements: null,
  isLoading: false,
  error: null,
  canAddPrompt: true,
  isPlanLocked: false,
  hasPrompt: false,
  blocksLaunch: true,
  reload: vi.fn(),
} as unknown as ScanPromptsState;

describe("AuditConfigurationForm section order", () => {
  it("puts prompts between Context and Entity configuration", () => {
    const { container } = render(
      <AuditConfigurationForm
        auditForm={auditForm}
        auditRunner={auditRunner}
        isStartDisabled={false}
        prompts={prompts}
        tierDurations={null}
        getAuthHeaders={vi.fn().mockResolvedValue({})}
        highConfidenceAccess={{
          isLocked: false,
          isLoading: false,
          currentPlanLabel: "Executive",
          eligiblePlanLabels: ["Specialist", "Executive"],
        }}
      />
    );

    const ids = Array.from(container.querySelectorAll("section[id]")).map((element) => element.id);
    expect(ids).toEqual([
      "audit-step-target",
      "audit-step-context",
      "audit-step-prompts",
      "audit-step-entities",
      "audit-step-depth",
      "audit-step-allowance",
      "audit-step-launch",
    ]);
  });
});
