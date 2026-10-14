import type { AnchorHTMLAttributes } from "react";
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditLaunchSection from "@/components/results/AuditLaunchSection";
import type { TierDurationsMap } from "@/hooks/useTierDurations";
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

// SIGV2-1177: the sentence states the measured p25..p75 range the page read
// once, in the shape `GET /api/v1/audit/tier-durations` serves it.
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

const buildProps = (overrides: Record<string, unknown> = {}) => {
  const { auditForm: auditFormRaw, auditRunner: auditRunnerRaw, ...restOverrides } = overrides;
  const auditFormOverrides = (auditFormRaw ?? {}) as Record<string, any>;
  const auditRunnerOverrides = (auditRunnerRaw ?? {}) as Record<string, any>;
  const auditForm = {
    isPreflightChecking: false,
    ...auditFormOverrides,
    form: { tier: "smart", ...(auditFormOverrides.form ?? {}) },
  };
  const auditRunner = {
    isLoading: false,
    isPolling: false,
    ...auditRunnerOverrides,
  };
  return {
    auditForm,
    auditRunner,
    isStartDisabled: false,
    tierDurations: TIER_DURATIONS,
    ...restOverrides,
  };
};

describe("AuditLaunchSection", () => {
  it("is the approved Launch section: the estimate sentence, Cancel and Start the audit", () => {
    render(<AuditLaunchSection {...buildProps()} />);

    expect(screen.getByRole("heading", { name: "Launch" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Typically around 12-21 min at the chosen depth, longer for a large site. You can leave the page - the result lands on the dashboard when it finishes."
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute("href", "/dashboard");
    expect(screen.getByRole("button", { name: "Start the audit" })).toBeEnabled();
  });

  // SIGV2-1177: a depth with no publishable measurement keeps the promise and
  // claims no duration, rather than borrowing another depth's range. The read
  // not having landed (`null`) falls back to the same sentence.
  it("claims no duration for a depth with no measured figure", () => {
    render(<AuditLaunchSection {...buildProps({ auditForm: { form: { tier: "lite" } } })} />);

    expect(
      screen.getByText(
        "You can leave the page - the result lands on the dashboard when it finishes."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/Typically around/)).not.toBeInTheDocument();
  });

  it("claims no duration while the measured read has not landed", () => {
    render(<AuditLaunchSection {...buildProps({ tierDurations: null })} />);

    expect(screen.queryByText(/Typically around/)).not.toBeInTheDocument();
  });

  it("disables start while the address is being checked", () => {
    render(
      <AuditLaunchSection
        {...buildProps({
          auditForm: { isPreflightChecking: true },
          isStartDisabled: true,
        })}
      />
    );
    expect(screen.getByRole("button", { name: /checking the address/i })).toBeDisabled();
  });

  it("disables start while the run is starting and while it is running", () => {
    const { unmount } = render(
      <AuditLaunchSection
        {...buildProps({ auditRunner: { isLoading: true }, isStartDisabled: true })}
      />
    );
    expect(screen.getByRole("button", { name: /starting/i })).toBeDisabled();
    unmount();

    render(
      <AuditLaunchSection
        {...buildProps({ auditRunner: { isPolling: true }, isStartDisabled: true })}
      />
    );
    expect(screen.getByRole("button", { name: /running/i })).toBeDisabled();
  });

  /* SIGV2-1171. `useAuditRunner` has always produced an error string for a
     refused start - validation, a missing target, a failed preflight, a
     project that could not be set up, a signed-out session - and nothing
     rendered it. Pressing Start and getting silence is exactly the "nothing
     happened" report this ticket exists for. */
  it("renders a refused start as an alert at the Start button", () => {
    render(
      <AuditLaunchSection
        {...buildProps({
          auditRunner: {
            error:
              "You do not have permission to add a project in this workspace, so the check did not start.",
          },
        })}
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The audit did not start");
    expect(alert).toHaveTextContent(/You do not have permission to add a project/);
    // At the action, not somewhere else on the page: the alert and the button
    // are siblings inside the Launch section.
    expect(alert.parentElement).toContainElement(
      screen.getByRole("button", { name: "Start the audit" })
    );
  });

  it("states a duplicate run persistently, not only as a toast", () => {
    render(
      <AuditLaunchSection
        {...buildProps({
          auditRunner: { isDuplicateAudit: true },
        })}
      />
    );

    expect(screen.getByRole("alert")).toHaveTextContent("An audit is already running");
  });

  it("stays quiet when nothing has failed", () => {
    render(<AuditLaunchSection {...buildProps()} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("states a failed draft save persistently at the launch row (SIGV2-1171)", () => {
    render(
      <AuditLaunchSection
        {...buildProps({
          auditForm: { draftSaveFailed: true },
        })}
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Your scan setup could not be saved");
    expect(alert).toHaveTextContent(/without leaving or reloading this page/);
    expect(alert.parentElement).toContainElement(
      screen.getByRole("button", { name: "Start the audit" })
    );
  });

  it("carries no progress surface: the run view owns the running state", () => {
    const { container } = render(
      <AuditLaunchSection {...buildProps({ auditRunner: { isPolling: true } })} />
    );

    expect(container.textContent).not.toMatch(/\d+%/);
    expect(container.querySelector(".motion-safe\\:animate-pulse")).toBeNull();
  });
});
