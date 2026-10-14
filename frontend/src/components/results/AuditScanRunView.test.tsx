import type { AnchorHTMLAttributes } from "react";
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditScanRunView from "@/components/results/AuditScanRunView";
import { tEn } from "@/test/i18nEn";
import type { AuditHistoryItem } from "@/types/auditWorkspace";

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

const stage = (id: string, status: string, reason: string | null = null) => ({
  id,
  status,
  attempt: 1,
  startedAt: null,
  completedAt: null,
  reason,
});

const buildProps = (overrides: Record<string, any> = {}) => {
  const { snapshot: snapshotOverrides, ...rest } = overrides;
  return {
    snapshot: {
      jobId: "job-1",
      phase: "running",
      targetLabel: "example.com",
      targetUrl: "https://example.com",
      tier: "smart",
      stages: [],
      error: null,
      startedAt: null,
      completedAt: null,
      auditId: null,
      ...(snapshotOverrides ?? {}),
    },
    debateProgress: null,
    completed: null,
    previousScan: null as AuditHistoryItem | null,
    visibility: null,
    scansUsed: null,
    scansRemaining: undefined,
    scansResetAt: null,
    onRetry: vi.fn(),
    onChangeOptions: vi.fn(),
    ...rest,
  } as any;
};

describe("AuditScanRunView running state", () => {
  it("names the five approved stages with the rule that status is per stage", () => {
    render(<AuditScanRunView {...buildProps()} />);

    expect(screen.getByRole("heading", { name: "Stages" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Signal reports status per stage, not a percentage. Each stage shows its honest state word."
      )
    ).toBeInTheDocument();
    for (const title of [
      "Crawl",
      "Technical signals",
      "Answer-engine measurement",
      "Competitor comparison",
      "Synthesis",
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it("renders no percentage and no progress bar", () => {
    const { container } = render(
      <AuditScanRunView
        {...buildProps({
          snapshot: {
            stages: [stage("signal_collection", "completed"), stage("measurement", "running")],
          },
        })}
      />
    );

    expect(container.textContent).not.toMatch(/\d+%/);
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
  });

  it("shows an honest state word per stage", () => {
    render(
      <AuditScanRunView
        {...buildProps({
          snapshot: {
            stages: [stage("signal_collection", "completed"), stage("measurement", "running")],
          },
        })}
      />
    );

    const crawl = document.querySelector('[data-stage="crawl"]');
    const engines = document.querySelector('[data-stage="answerEngines"]');
    const synthesis = document.querySelector('[data-stage="synthesis"]');
    expect(crawl).toHaveAttribute("data-stage-state", "completed");
    expect(crawl?.textContent).toContain("succeeded");
    expect(engines).toHaveAttribute("data-stage-state", "running");
    expect(synthesis?.textContent).toContain("queued");
  });

  it("carries no hardcoded mockup counts in the stage descriptions", () => {
    const { container } = render(<AuditScanRunView {...buildProps()} />);

    expect(container.textContent).toContain("Key pages fetched and rendered");
    expect(container.textContent).not.toMatch(/24 key pages|30 prompts|7 engines|4 competitors/);
  });

  it("derives the review-step count for Synthesis when the debate reports one", () => {
    render(
      <AuditScanRunView
        {...buildProps({
          debateProgress: {
            steps: [{ status: "completed" }, { status: "running" }, { status: "pending" }],
          },
        })}
      />
    );

    expect(screen.getByText("1 of 3 review steps done")).toBeInTheDocument();
  });

  // SIGV2-1162: the card contradicted itself during a live demo. The counter
  // and the state word read different sources (the debate event stream and
  // the projected stage states), and the word said "queued" for a row whose
  // debate stage had already completed.
  it("does not call Synthesis queued while its own counter reports every review step done", () => {
    render(
      <AuditScanRunView
        {...buildProps({
          snapshot: {
            stages: [
              stage("signal_collection", "completed"),
              stage("measurement", "completed"),
              stage("analysis", "completed"),
              stage("report", "pending"),
            ],
          },
          debateProgress: {
            steps: [{ status: "completed" }, { status: "completed" }, { status: "completed" }],
          },
        })}
      />
    );

    const synthesis = document.querySelector('[data-stage="synthesis"]');
    expect(synthesis?.textContent).toContain("3 of 3 review steps done");
    expect(synthesis).toHaveAttribute("data-stage-state", "running");
    expect(synthesis?.textContent).not.toContain("queued");
  });

  it("reports Synthesis as succeeded once the report stage completes too", () => {
    render(
      <AuditScanRunView
        {...buildProps({
          snapshot: {
            stages: [
              stage("signal_collection", "completed"),
              stage("measurement", "completed"),
              stage("analysis", "completed"),
              stage("report", "completed"),
            ],
          },
          debateProgress: {
            steps: [{ status: "completed" }, { status: "completed" }, { status: "completed" }],
          },
        })}
      />
    );

    const synthesis = document.querySelector('[data-stage="synthesis"]');
    expect(synthesis).toHaveAttribute("data-stage-state", "completed");
    expect(synthesis?.textContent).toContain("succeeded");
  });

  it("states that it is safe to leave the page", () => {
    render(<AuditScanRunView {...buildProps()} />);

    expect(screen.getByText("Safe to leave")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This scan runs on our side. Come back any time - the state is saved and the page resumes where it is."
      )
    ).toBeInTheDocument();
  });
});

describe("AuditScanRunView succeeded state", () => {
  const succeeded = (overrides: Record<string, any> = {}) =>
    buildProps({
      snapshot: {
        phase: "succeeded",
        startedAt: "2026-09-01T10:00:00Z",
        completedAt: "2026-09-01T10:14:00Z",
        auditId: 42,
        stages: [
          stage("signal_collection", "completed"),
          stage("measurement", "completed"),
          stage("analysis", "completed"),
          stage("report", "completed"),
        ],
      },
      completed: { auditId: 42, aioScore: 64, seoScore: 74 },
      scansUsed: 144,
      scansRemaining: 1856,
      ...overrides,
    });

  it("reports the real duration and the allowance in the approved one-liner", () => {
    const { container } = render(<AuditScanRunView {...succeeded()} />);
    const success = container.querySelector('[data-signal-alert="success"]');
    expect(success).toHaveAttribute("role", "status");
    expect(success?.querySelector("svg")).not.toBeNull();

    // Approved shape: "Scan finished in 14 minutes. 1 scan used, 1,856 left in
    // your current 30-day window." The limit and the reset date the shared
    // allowance note adds elsewhere are not on this surface (SIGV2-1123). The
    // window is the backend's rolling 30 days, never "this month" (SIGV2-1135).
    expect(container.textContent).toContain(
      "Scan finished in 14 minutes. 1 scan used, 1,856 left in your current 30-day window."
    );
    expect(container.textContent).not.toMatch(/this month/i);
    expect(container.textContent).not.toMatch(/of 2000/);
    expect(container.textContent).not.toMatch(/resets/i);
  });

  it("states only the scan used when the plan has no cap or no known allowance", () => {
    const { container: unlimited } = render(
      <AuditScanRunView {...succeeded({ scansRemaining: null })} />
    );
    expect(unlimited.textContent).toContain("1 scan used, unlimited scans on your plan.");

    const { container: unknown } = render(
      <AuditScanRunView {...succeeded({ scansRemaining: undefined, scansUsed: null })} />
    );
    expect(unknown.textContent).toContain("1 scan used.");
    expect(unknown.textContent).not.toMatch(/left in your current 30-day window/);
  });

  it("drops the duration when the job did not report both timestamps", () => {
    render(
      <AuditScanRunView {...succeeded({ snapshot: { phase: "succeeded", completedAt: null } })} />
    );

    expect(screen.getByText(/Scan finished\./)).toBeInTheDocument();
    expect(screen.queryByText(/Scan finished in/)).not.toBeInTheDocument();
  });

  it("shows the two scores the audit produces", () => {
    render(<AuditScanRunView {...succeeded()} />);

    expect(screen.getByRole("heading", { name: "New scores" })).toBeInTheDocument();
    expect(screen.getByText("AIO score")).toBeInTheDocument();
    expect(screen.getByText("SEO score")).toBeInTheDocument();
  });

  it("keeps the AI visibility stat out when the scan has no project behind it", () => {
    const { container } = render(<AuditScanRunView {...succeeded({ visibility: null })} />);

    expect(container.querySelectorAll("[data-scan-stat]")).toHaveLength(2);
    expect(screen.queryByText("AI visibility")).not.toBeInTheDocument();
  });

  it("states the project's measured AI visibility with its real delta and date", () => {
    const { container } = render(
      <AuditScanRunView
        {...succeeded({
          visibility: {
            state: "measured",
            percent: 41,
            delta: 5,
            measuredAt: "2026-08-29T09:00:00Z",
          },
        })}
      />
    );

    const visibility = container.querySelector('[data-scan-stat="aiVisibility"]')!;
    expect(screen.getByText("AI visibility")).toBeInTheDocument();
    expect(visibility.textContent).toContain("41%");
    expect(visibility.querySelector("[data-scan-delta]")).toHaveAttribute("data-scan-delta", "up");
    expect(visibility.textContent).toContain("+5");
    expect(visibility.textContent).toContain("\u2191");
    // The figure is the project's monitoring measurement, not this scan's, and
    // the stat says so with the measurement's own date.
    // SIGV2-1295: the caption says what the score means, in the same few words
    // its neighbours use. Which run produced it is a tooltip now, because
    // carrying that sentence inline wrapped to four lines and lifted the row.
    expect(screen.getByText("Visibility across the prompts you track")).toBeInTheDocument();
    expect(screen.queryByText(/not by this scan/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Where this score comes from")).toBeInTheDocument();
  });

  it("prints the visibility figure with no delta when nothing comparable backs one", () => {
    const { container } = render(
      <AuditScanRunView
        {...succeeded({
          previousScan: null,
          visibility: { state: "measured", percent: 41, delta: null, measuredAt: null },
        })}
      />
    );

    const visibility = container.querySelector('[data-scan-stat="aiVisibility"]')!;
    expect(visibility.textContent).toContain("41%");
    expect(visibility.querySelector("[data-scan-delta]")).toBeNull();
    expect(screen.getByText("Visibility across the prompts you track")).toBeInTheDocument();
    expect(screen.getByLabelText("Where this score comes from")).toBeInTheDocument();
  });

  it("says not measured, never a zero, when the project has no completed run", () => {
    const { container } = render(
      <AuditScanRunView {...succeeded({ visibility: { state: "unmeasured", reason: "no_run" } })} />
    );

    const visibility = container.querySelector('[data-scan-stat="aiVisibility"]')!;
    expect(visibility.textContent).toContain("Not measured");
    expect(visibility.textContent).not.toMatch(/\d/);
    expect(visibility.querySelector("[data-scan-delta]")).toBeNull();
    expect(
      screen.getByText("No completed AI visibility monitoring run for this project yet")
    ).toBeInTheDocument();
  });

  it("names the plan as the reason when monitoring is not included", () => {
    render(
      <AuditScanRunView {...succeeded({ visibility: { state: "unmeasured", reason: "locked" } })} />
    );

    expect(screen.getByText("Not measured")).toBeInTheDocument();
    expect(
      screen.getByText("AI visibility monitoring is not included in your plan")
    ).toBeInTheDocument();
  });

  it("says there is no baseline rather than implying a delta on a first scan", () => {
    render(<AuditScanRunView {...succeeded()} />);

    expect(
      screen.getByText(
        "This is the first scan for this target, so there is nothing to compare yet."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "There is no earlier scan for this target, so nothing is reported as changed."
      )
    ).toBeInTheDocument();
  });

  const previousScan = (overrides: Record<string, any> = {}): AuditHistoryItem =>
    ({
      id: 41,
      url: "https://example.com",
      targetUrl: "https://example.com",
      targetName: null,
      auditTargetType: "website",
      targetMetadata: {},
      aeoScore: 60,
      geoScore: 62,
      seoScore: 72,
      status: "completed",
      auditType: "SMART",
      createdAt: "2026-08-18T10:00:00Z",
      fullReport: null,
      ...overrides,
    }) as AuditHistoryItem;

  it("derives one line per moved score against the previous scan", () => {
    render(<AuditScanRunView {...succeeded({ previousScan: previousScan() })} />);

    expect(screen.getByRole("heading", { name: "What changed" })).toBeInTheDocument();
    expect(screen.getByText("AIO score moved from 61 to 64.")).toBeInTheDocument();
    expect(screen.getByText("SEO score moved from 72 to 74.")).toBeInTheDocument();
  });

  it("carries a signed delta and a direction on every stat (SIGV2-1123)", () => {
    const { container } = render(
      <AuditScanRunView {...succeeded({ previousScan: previousScan() })} />
    );

    const aio = container.querySelector('[data-scan-stat="aio"]')!;
    const seo = container.querySelector('[data-scan-stat="seo"]')!;
    // AIO 61 -> 64, SEO 72 -> 74: both signed, both with a direction arrow.
    expect(aio.querySelector("[data-scan-delta]")).toHaveAttribute("data-scan-delta", "up");
    expect(aio.textContent).toContain("+3");
    expect(aio.textContent).toContain("\u2191");
    expect(seo.querySelector("[data-scan-delta]")).toHaveAttribute("data-scan-delta", "up");
    expect(seo.textContent).toContain("+2");
    expect(seo.textContent).toContain("\u2191");
  });

  it("signs a fall downwards and states no change as a measured zero", () => {
    const { container } = render(
      <AuditScanRunView
        {...succeeded({
          // AIO previous 70 (the mean of 68 and 72) against this run's 64;
          // SEO unchanged at 74.
          previousScan: previousScan({ aeoScore: 68, geoScore: 72, seoScore: 74 }),
        })}
      />
    );

    const aio = container.querySelector('[data-scan-stat="aio"]')!;
    const seo = container.querySelector('[data-scan-stat="seo"]')!;
    expect(aio.querySelector("[data-scan-delta]")).toHaveAttribute("data-scan-delta", "down");
    expect(aio.textContent).toContain("-6");
    expect(aio.textContent).toContain("\u2193");
    // "No movement" is a measured outcome, so it is printed; it carries no
    // arrow because there is no direction to state.
    expect(seo.querySelector("[data-scan-delta]")).toHaveAttribute("data-scan-delta", "unchanged");
    expect(seo.textContent).toContain("0");
    expect(seo.textContent).not.toMatch(/[\u2191\u2193]/);
  });

  it("prints no delta at all when the target has no comparable earlier scan", () => {
    const { container } = render(<AuditScanRunView {...succeeded()} />);

    expect(container.querySelector("[data-scan-delta]")).toBeNull();
  });

  it("offers the four approved actions", () => {
    render(<AuditScanRunView {...succeeded()} />);

    expect(screen.getByRole("link", { name: "Open AIO detail" })).toHaveAttribute(
      "href",
      "/dashboard/audit/42#report-sec-aeo"
    );
    expect(screen.getByRole("link", { name: "Open SEO detail" })).toHaveAttribute(
      "href",
      "/dashboard/audit/42#report-sec-seo"
    );
    expect(screen.getByRole("link", { name: "Review the fix plan" })).toHaveAttribute(
      "href",
      "/dashboard/audit/42#report-sec-fixes"
    );
    expect(screen.getByRole("link", { name: "Back to dashboard" })).toHaveAttribute(
      "href",
      "/dashboard"
    );
  });

  // SIGV2-1164: the dashboard action means the scan's own project dashboard,
  // the way the approved design links it, not the workspace overview.
  it("points the dashboard action at the project dashboard it is given", () => {
    render(<AuditScanRunView {...succeeded({ dashboardHref: "/dashboard/projects/7" })} />);

    expect(screen.getByRole("link", { name: "Back to dashboard" })).toHaveAttribute(
      "href",
      "/dashboard/projects/7"
    );
  });
});

describe("AuditScanRunView failed state", () => {
  const failed = (overrides: Record<string, any> = {}) =>
    buildProps({
      snapshot: {
        phase: "failed",
        error: "Two providers timed out.",
        stages: [
          stage("signal_collection", "completed"),
          stage("measurement", "failed", "provider_timeout"),
        ],
      },
      ...overrides,
    });

  it("names the stage that failed and keeps the earlier stages", () => {
    render(<AuditScanRunView {...failed()} />);
    expect(screen.getByRole("alert")).toHaveAttribute("data-signal-alert", "danger");
    expect(screen.getByRole("alert").querySelector("svg")).not.toBeNull();

    expect(screen.getByText(/The Technical signals stage could not finish\./)).toBeInTheDocument();
    expect(screen.getByText(/Two providers timed out\./)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What happened" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Stages before the failure completed and are kept. The failure is in the stage marked below."
      )
    ).toBeInTheDocument();
    expect(document.querySelector('[data-stage="crawl"]')).toHaveAttribute(
      "data-stage-state",
      "completed"
    );
    expect(document.querySelector('[data-stage="synthesis"]')).toHaveAttribute(
      "data-stage-state",
      "pending"
    );
  });

  it("never promises a refund the backend does not give", () => {
    const { container } = render(<AuditScanRunView {...failed()} />);

    expect(container.textContent).not.toMatch(/nothing was charged/i);
    expect(container.textContent).not.toMatch(/did not use an audit/i);
    expect(container.textContent).not.toMatch(/credit/i);
  });

  it("offers retry and change options", () => {
    const props = failed();
    render(<AuditScanRunView {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Retry scan" }));
    expect(props.onRetry).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Change scan options" }));
    expect(props.onChangeOptions).toHaveBeenCalledTimes(1);
  });
});
