import type { AnchorHTMLAttributes } from "react";
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditDepthSection from "@/components/results/AuditDepthSection";
import AuditLaunchSection from "@/components/results/AuditLaunchSection";
import { useAuditForm } from "@/hooks/useAuditForm";
import { formatTierDurationRange, type TierDurationsMap } from "@/hooks/useTierDurations";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// SIGV2-1177: the figures the page states are the measured p25..p75 ranges
// the endpoint serves, in the shape `GET /api/v1/audit/tier-durations`
// returns them. The fixture stands in for the page-level read the real app
// makes once and shares between the depth table and the Launch sentence.
const TIER_DURATIONS: TierDurationsMap = {
  fast: {
    low_minutes: 4,
    high_minutes: 9,
    median_minutes: 6,
    sample_size: 41,
    window_days: 90,
    computed_at: "2026-10-13T08:00:00Z",
  },
  smart: {
    low_minutes: 12,
    high_minutes: 21,
    median_minutes: 16,
    sample_size: 58,
    window_days: 90,
    computed_at: "2026-10-13T08:00:00Z",
  },
  deep_judgment: {
    low_minutes: 33,
    high_minutes: 52,
    median_minutes: 41,
    sample_size: 26,
    window_days: 90,
    computed_at: "2026-10-13T08:00:00Z",
  },
};

const buildProps = (overrides: Record<string, any> = {}) => {
  const { auditForm: auditFormRaw, ...rest } = overrides;
  const auditFormOverrides = (auditFormRaw ?? {}) as Record<string, any>;
  return {
    auditForm: {
      setFormValue: vi.fn(),
      ...auditFormOverrides,
      form: { tier: "fast", ...(auditFormOverrides.form ?? {}) },
    },
    auditRunner: { isLoading: false, isPolling: false },
    highConfidenceAccess: {
      isLocked: false,
      isLoading: false,
      currentPlanLabel: "Specialist",
      eligiblePlanLabels: ["Executive"],
    },
    highConfidenceEligibleLabel: "Executive",
    tierDurations: TIER_DURATIONS,
    ...rest,
  } as any;
};

describe("AuditDepthSection", () => {
  it("states the trade-off rather than only naming the depths", () => {
    render(<AuditDepthSection {...buildProps()} />);

    expect(screen.getByRole("heading", { name: "How thorough" })).toBeInTheDocument();
    expect(
      screen.getByText("Depth trades coverage for time. The trade-off is stated, not just named.")
    ).toBeInTheDocument();
  });

  it("carries selectable cards with what you get per tier", () => {
    render(<AuditDepthSection {...buildProps()} />);

    expect(screen.getByText("Top pages only, core engines")).toBeInTheDocument();
    expect(
      screen.getByText("Key pages, all measured engines, competitor comparison")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Whole site, all engines, per-prompt detail and agent review")
    ).toBeInTheDocument();
  });

  // SIGV2-1177: each card states the measured p25..p75 range the page read
  // once, so the cards cannot disagree with the Launch sentence.
  it("takes typical time from the measured tier durations", () => {
    render(<AuditDepthSection {...buildProps()} />);

    expect(screen.getByText("4-9 min")).toBeInTheDocument();
    expect(screen.getByText("12-21 min")).toBeInTheDocument();
    expect(screen.getByText("33-52 min")).toBeInTheDocument();
  });

  it("states no duration for a tier with no published measurement", () => {
    render(
      <AuditDepthSection
        {...buildProps({
          tierDurations: {
            smart: TIER_DURATIONS.smart,
          },
        })}
      />
    );

    expect(screen.getByText("12-21 min")).toBeInTheDocument();
    expect(screen.queryByText("4-9 min")).not.toBeInTheDocument();
    expect(screen.queryByText("33-52 min")).not.toBeInTheDocument();
  });

  it("states nothing while the read has not landed", () => {
    render(<AuditDepthSection {...buildProps({ tierDurations: null })} />);

    expect(screen.queryByText(/min/)).not.toBeInTheDocument();
  });

  it("records the chosen depth", () => {
    const props = buildProps();
    render(<AuditDepthSection {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Depth Smart" }));
    expect(props.auditForm.setFormValue).toHaveBeenCalledWith("tier", "smart");
  });

  it("locks Deep judgment with the upgrade path when the plan is not eligible", () => {
    render(
      <AuditDepthSection
        {...buildProps({
          highConfidenceAccess: {
            isLocked: true,
            isLoading: false,
            currentPlanLabel: "Specialist",
            eligiblePlanLabels: ["Executive"],
          },
        })}
      />
    );

    expect(screen.getByRole("button", { name: "Depth Deep judgment locked" })).toBeDisabled();
    expect(screen.getByText("Deep judgment is not available on Specialist")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review plans and upgrades" })).toHaveAttribute(
      "href",
      "/dashboard/billing"
    );
  });
});

/**
 * SIGV2-1177: choosing a depth must change the duration the page states. The
 * live figure is the Launch section's sentence, exactly as in the approved
 * mockup (`#est-runtime` in Signal Audit.html); the table above it compares
 * all three depths and is static by design, with only the chosen depth's name
 * emphasised.
 *
 * The figures come from the one measured map the page fetched, handed to both
 * sections here the way `AuditConfigurationForm` hands it in the app, so this
 * test checks the wiring: the sentence and the column read the same figure.
 */
describe("the chosen depth and the launch estimate", () => {
  const Harness = () => {
    const auditForm = useAuditForm({ getAuthHeaders: async () => ({}) });
    const auditRunner = { isLoading: false, isPolling: false };
    return (
      <>
        <AuditDepthSection
          auditForm={auditForm}
          auditRunner={auditRunner}
          highConfidenceAccess={{
            isLocked: false,
            isLoading: false,
            currentPlanLabel: "Executive",
            eligiblePlanLabels: ["Executive"],
          }}
          highConfidenceEligibleLabel="Executive"
          tierDurations={TIER_DURATIONS}
        />
        <AuditLaunchSection
          auditForm={auditForm}
          auditRunner={auditRunner}
          isStartDisabled={false}
          tierDurations={TIER_DURATIONS}
        />
      </>
    );
  };

  const launchEstimate = () =>
    screen
      .getByText(/Typically around .* at the chosen depth/)
      .textContent?.match(/Typically around (.*) at the chosen depth/)?.[1]
      ?.trim();

  it("restates the measured range for each depth the customer picks", () => {
    window.localStorage.clear();
    render(<Harness />);

    expect(launchEstimate()).toBe("4-9 min");

    fireEvent.click(screen.getByRole("button", { name: "Depth Deep judgment" }));
    expect(launchEstimate()).toBe("33-52 min");

    fireEvent.click(screen.getByRole("button", { name: "Depth Smart" }));
    expect(launchEstimate()).toBe("12-21 min");

    fireEvent.click(screen.getByRole("button", { name: "Depth Fast" }));
    expect(launchEstimate()).toBe("4-9 min");
  });

  it("states a different measured range for each depth, so the choice is never cosmetic", () => {
    const stated = [
      formatTierDurationRange(TIER_DURATIONS.fast),
      formatTierDurationRange(TIER_DURATIONS.smart),
      formatTierDurationRange(TIER_DURATIONS.deep_judgment),
    ];
    expect(new Set(stated).size).toBe(stated.length);
  });

  // The figure is an estimate, and the sentence has to say so in words rather
  // than leaving the range to carry it (SIGV2-1161).
  it("words the sentence as a typical duration that can be longer", () => {
    window.localStorage.clear();
    render(<Harness />);

    const sentence = screen.getByText(/Typically around/).textContent ?? "";
    expect(sentence).toContain("Typically around");
    expect(sentence).toContain("longer for a large site");
  });
});
