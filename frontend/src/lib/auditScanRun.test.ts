import { describe, expect, it } from "vitest";

import {
  findFailedStageRow,
  findPreviousScan,
  resolveResetInDays,
  resolveScanDuration,
  resolveScanStageRows,
  resolveScanVisibilityStat,
  type AuditStageStatus,
} from "@/lib/auditScanRun";
import type { AuditHistoryItem } from "@/types/auditWorkspace";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

const stage = (id: string, status: AuditStageStatus["status"], reason: string | null = null) => ({
  id,
  status,
  attempt: 1,
  startedAt: null,
  completedAt: null,
  reason,
});

const historyItem = (overrides: Partial<AuditHistoryItem>): AuditHistoryItem =>
  ({
    id: 1,
    url: "https://example.com",
    auditTargetType: "website",
    targetName: null,
    targetUrl: "https://example.com",
    targetMetadata: {},
    geoScore: 40,
    seoScore: 70,
    aeoScore: 60,
    status: "completed",
    auditType: "SMART",
    createdAt: "2026-09-01T10:00:00Z",
    fullReport: null,
    ...overrides,
  }) as AuditHistoryItem;

describe("resolveScanStageRows", () => {
  it("reports all five approved rows as queued when no stage evidence arrived", () => {
    const rows = resolveScanStageRows([]);

    expect(rows.map((row) => row.id)).toEqual([
      "crawl",
      "technical",
      "answerEngines",
      "competitors",
      "synthesis",
    ]);
    expect(rows.every((row) => row.status === "pending")).toBe(true);
  });

  it("reads crawl from signal_collection and the three measurement rows from measurement", () => {
    const rows = resolveScanStageRows([
      stage("signal_collection", "completed"),
      stage("measurement", "running"),
      stage("analysis", "pending"),
      stage("report", "pending"),
    ]);

    expect(rows[0]).toMatchObject({ id: "crawl", status: "completed" });
    expect(rows[1]).toMatchObject({ id: "technical", status: "running" });
    expect(rows[2]).toMatchObject({ id: "answerEngines", status: "running" });
    expect(rows[3]).toMatchObject({ id: "competitors", status: "running" });
    expect(rows[4]).toMatchObject({ id: "synthesis", status: "pending" });
  });

  it("holds Synthesis open until the report stage itself completes", () => {
    const debateDone = resolveScanStageRows([
      stage("analysis", "completed"),
      stage("report", "running"),
    ]);
    expect(debateDone[4].status).toBe("running");

    const allDone = resolveScanStageRows([
      stage("analysis", "completed"),
      stage("report", "completed"),
    ]);
    expect(allDone[4].status).toBe("completed");
  });

  // SIGV2-1162. The backend completes `analysis` the moment the debate
  // returns (audit_runner.py, stage_completed analysis) and only starts
  // `report` after the post-analysis work (queue_worker.py, stage_started
  // report), so every scan passes through this pair. The row said "queued"
  // for that whole window while its own counter said all review steps were
  // done, inside the same card.
  it("reports Synthesis as running once the debate stage completed and report has not started", () => {
    const rows = resolveScanStageRows([
      stage("signal_collection", "completed"),
      stage("measurement", "completed"),
      stage("analysis", "completed"),
      stage("report", "pending"),
    ]);

    expect(rows[4]).toMatchObject({ id: "synthesis", status: "running" });
  });

  it("reports Synthesis as succeeded once both of its stages completed", () => {
    const rows = resolveScanStageRows([
      stage("signal_collection", "completed"),
      stage("measurement", "completed"),
      stage("analysis", "completed"),
      stage("report", "completed"),
    ]);

    expect(rows.every((row) => row.status === "completed")).toBe(true);
    expect(rows[4]).toMatchObject({ id: "synthesis", status: "completed" });
  });

  it("never reads a row with one finished and one skipped stage as queued", () => {
    // Scrape failure skips the debate and still assembles a report, so the
    // row is finished but did not run in full. "queued" would be a lie about
    // a terminal scan; "succeeded" would be a lie about the skipped stage.
    // The backend marks this skip "upstream_data_unavailable", the reason it
    // emits when the stage did not run because its input failed.
    const rows = resolveScanStageRows([
      stage("analysis", "skipped", "upstream_data_unavailable"),
      stage("report", "completed"),
    ]);

    expect(rows[4]).toMatchObject({ id: "synthesis", status: "degraded" });
  });

  it("reads a designed skip as skipped, never a word implying failure", () => {
    // A quick scan skips the debate on purpose (audit_runner.py emits
    // stage_skipped analysis with reason "deterministic_quick_scan") and the
    // report still completes, so Synthesis reads "skipped" - the neutral word
    // for a step that did not run - not "degraded", which claims something
    // went wrong on a healthy scan.
    const rows = resolveScanStageRows([
      stage("analysis", "skipped", "deterministic_quick_scan"),
      stage("report", "completed"),
    ]);

    expect(rows[4]).toMatchObject({ id: "synthesis", status: "skipped" });
    expect(rows[4].status).not.toBe("degraded");
    expect(rows[4].status).not.toBe("failed");
  });

  it("carries the failure reason and leaves later rows queued", () => {
    const rows = resolveScanStageRows([
      stage("signal_collection", "completed"),
      stage("measurement", "failed", "provider_timeout"),
    ]);

    expect(findFailedStageRow(rows)).toMatchObject({
      id: "technical",
      status: "failed",
      reason: "provider_timeout",
    });
    expect(rows[4].status).toBe("pending");
  });

  it("never upgrades missing evidence to completed", () => {
    const rows = resolveScanStageRows([stage("signal_collection", "unknown")]);
    expect(rows[0].status).toBe("unknown");
  });
});

describe("resolveScanDuration", () => {
  it("returns null when either timestamp is missing", () => {
    expect(resolveScanDuration(null, "2026-09-01T10:14:00Z")).toBeNull();
    expect(resolveScanDuration("2026-09-01T10:00:00Z", null)).toBeNull();
  });

  it("reports minutes for a long run and seconds for a short one", () => {
    expect(resolveScanDuration("2026-09-01T10:00:00Z", "2026-09-01T10:14:00Z")).toEqual({
      unit: "minutes",
      count: 14,
    });
    expect(resolveScanDuration("2026-09-01T10:00:00Z", "2026-09-01T10:00:42Z")).toEqual({
      unit: "seconds",
      count: 42,
    });
  });

  it("refuses a completed_at that precedes started_at", () => {
    expect(resolveScanDuration("2026-09-01T10:14:00Z", "2026-09-01T10:00:00Z")).toBeNull();
  });
});

describe("resolveResetInDays", () => {
  it("returns whole days remaining, and null when nothing is known", () => {
    const now = new Date("2026-09-01T00:00:00Z");
    expect(resolveResetInDays("2026-09-13T00:00:00Z", now)).toBe(12);
    expect(resolveResetInDays(null, now)).toBeNull();
    expect(resolveResetInDays("2026-08-01T00:00:00Z", now)).toBe(0);
  });
});

describe("findPreviousScan", () => {
  it("returns the most recent earlier scan for the same address", () => {
    const history = [
      historyItem({ id: 3, createdAt: "2026-09-10T10:00:00Z" }),
      historyItem({ id: 2, createdAt: "2026-09-05T10:00:00Z" }),
      historyItem({ id: 9, targetUrl: "https://other.example", createdAt: "2026-09-20T10:00:00Z" }),
    ];

    expect(
      findPreviousScan(history, { auditId: 3, url: "https://example.com", targetName: "" })?.id
    ).toBe(2);
  });

  it("matches on www and scheme differences", () => {
    const history = [historyItem({ id: 2, targetUrl: "http://www.example.com/" })];
    expect(
      findPreviousScan(history, { auditId: 5, url: "https://example.com", targetName: "" })?.id
    ).toBe(2);
  });

  it("matches a brand target on its name", () => {
    const history = [historyItem({ id: 4, targetUrl: "", url: "", targetName: "Acme" })];
    expect(findPreviousScan(history, { auditId: null, url: "", targetName: "acme" })?.id).toBe(4);
  });

  it("returns null when the target has never been scanned before", () => {
    const history = [historyItem({ id: 2, targetUrl: "https://other.example" })];
    expect(
      findPreviousScan(history, { auditId: 1, url: "https://example.com", targetName: "" })
    ).toBeNull();
    expect(findPreviousScan([], { auditId: 1, url: "", targetName: "" })).toBeNull();
  });
});

describe("resolveScanVisibilityStat", () => {
  const summary = (overrides: Partial<VisibilitySummaryResponse> = {}): VisibilitySummaryResponse =>
    ({
      project_id: 7,
      entitlements: { is_locked: false },
      queries_configured: 4,
      providers: ["google"],
      visibility_score: 41.4,
      score_breakdown: null,
      trend_delta: 5.2,
      completed_checks: 12,
      pending_checks: 0,
      cited_checks: 5,
      total_checks: 12,
      last_updated_at: "2026-08-29T09:00:00Z",
      provider_breakdown: [],
      queries: [],
      ...overrides,
    }) as VisibilitySummaryResponse;

  it("reports the measured figure, its own delta and its own date", () => {
    expect(resolveScanVisibilityStat(summary())).toEqual({
      state: "measured",
      percent: 41,
      delta: 5,
      measuredAt: "2026-08-29T09:00:00Z",
    });
  });

  it("drops the delta when the series carries no comparable previous point", () => {
    expect(resolveScanVisibilityStat(summary({ trend_delta: null }))).toEqual({
      state: "measured",
      percent: 41,
      delta: null,
      measuredAt: "2026-08-29T09:00:00Z",
    });
  });

  it("keeps a measured zero move, which is an outcome and not a missing one", () => {
    expect(resolveScanVisibilityStat(summary({ trend_delta: 0 }))?.delta).toBe(0);
  });

  it("is unmeasured, never a zero, without a completed run", () => {
    expect(resolveScanVisibilityStat(summary({ completed_checks: 0 }))).toEqual({
      state: "unmeasured",
      reason: "no_run",
    });
    expect(resolveScanVisibilityStat(summary({ visibility_score: null }))).toEqual({
      state: "unmeasured",
      reason: "no_run",
    });
  });

  it("names the plan when monitoring is not entitled", () => {
    expect(
      resolveScanVisibilityStat(
        summary({ entitlements: { is_locked: true } as VisibilitySummaryResponse["entitlements"] })
      )
    ).toEqual({ state: "unmeasured", reason: "locked" });
  });

  it("states nothing at all when there is no summary to read", () => {
    expect(resolveScanVisibilityStat(null)).toBeNull();
    expect(resolveScanVisibilityStat(undefined)).toBeNull();
  });
});
