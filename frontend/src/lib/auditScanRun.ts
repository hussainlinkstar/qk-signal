import type { AuditHistoryItem } from "@/types/auditWorkspace";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

/**
 * The scan run view (approved mockup: Signal Audit Run.html) in three states.
 * `idle` means no run is attached, so the start-scan page shows the form.
 */
export type ScanRunPhase = "idle" | "running" | "succeeded" | "failed";

/**
 * Backend stage state machine (SIGV2-1021,
 * backend/services/audit_job_event_service.py). `unknown` means the durable
 * stage evidence expired, never that the stage completed.
 */
export type AuditStageState =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "degraded"
  | "unknown";

export type AuditStageStatus = {
  id: string;
  status: AuditStageState;
  attempt: number;
  startedAt: string | null;
  completedAt: string | null;
  reason: string | null;
};

/** The five stage rows of the approved run view, in pipeline order. */
export type ScanStageRowId = "crawl" | "technical" | "answerEngines" | "competitors" | "synthesis";

export type ScanStageRow = {
  id: ScanStageRowId;
  status: AuditStageState;
  /** Short machine reason the backend attributed to the failure, when it sent one. */
  reason: string | null;
};

export const SCAN_STAGE_ROW_IDS: readonly ScanStageRowId[] = [
  "crawl",
  "technical",
  "answerEngines",
  "competitors",
  "synthesis",
];

/**
 * Which backend stage each approved row reads its state from.
 *
 * The backend reports four stages, not five: `signal_collection`,
 * `measurement`, `analysis`, `report`. `measurement` is one stage covering the
 * parallel performance/network/answerability/visibility/competitor gather, so
 * the three rows the approved design names separately (technical signals,
 * answer-engine measurement, competitor comparison) all read that single
 * stage. That is the finest granularity the run actually reports; inventing an
 * independent state per row would assert evidence we do not have. `synthesis`
 * covers the AI debate (`analysis`) and the scoring/assembly (`report`)
 * together, because the approved description ("New scores, deltas and the
 * updated fix list") is the output of both.
 */
const ROW_SOURCE_STAGES: Record<ScanStageRowId, readonly string[]> = {
  crawl: ["signal_collection"],
  technical: ["measurement"],
  answerEngines: ["measurement"],
  competitors: ["measurement"],
  synthesis: ["analysis", "report"],
};

const stageById = (stages: AuditStageStatus[]): Map<string, AuditStageStatus> =>
  new Map(stages.map((stage) => [stage.id, stage]));

/**
 * `stage_skipped` reasons (audit_runner.py) that mean the stage did not run
 * because upstream evidence was missing, not by design. The designed skips -
 * `deterministic_quick_scan` (the quick-scan path), `brand_target`,
 * `not_applicable` - are honest "skipped" rows. Only a skip the backend
 * attributed to missing upstream data reads "degraded", because that is the
 * one case where something actually went wrong.
 */
const SKIP_FAILURE_REASONS: ReadonlySet<string> = new Set(["upstream_data_unavailable"]);

/**
 * Combine the source stages of one row into a single honest state word.
 * Order of precedence puts the worst real outcome first so a failure is never
 * hidden behind a later stage that has not started.
 *
 * A row whose sources have not all reached the same state is still in
 * progress, never queued (SIGV2-1162). Synthesis is the only row with more
 * than one source, and the backend completes `analysis` the moment the debate
 * returns while `report` only starts after the post-analysis work
 * (grounding, entity enhancement, scoring, assembly). Reading "queued" for
 * that whole window contradicted the row's own "N of M review steps done"
 * counter inside the same card.
 */
const combineStates = (stages: Pick<AuditStageStatus, "status" | "reason">[]): AuditStageState => {
  const states = stages.map((stage) => stage.status);
  if (states.length === 0) return "pending";
  if (states.includes("failed")) return "failed";
  if (states.includes("running")) return "running";
  if (states.includes("degraded")) return "degraded";
  if (states.every((state) => state === "completed")) return "completed";
  const skipped = stages.filter((stage) => stage.status === "skipped");
  // Every source terminal and at least one skipped: the row did not run in
  // full. A designed skip is neutral "skipped"; a failure skip is "degraded".
  // Neither is upgraded to "completed", because a skipped stage did not
  // produce its output.
  if (skipped.length > 0 && states.every((state) => state === "completed" || state === "skipped")) {
    return skipped.some((stage) => stage.reason && SKIP_FAILURE_REASONS.has(stage.reason))
      ? "degraded"
      : "skipped";
  }
  // At least one source finished or was skipped while another has not
  // started: the row has started, so it reads running rather than queued
  // (SIGV2-1162).
  if (states.some((state) => state === "completed" || state === "skipped")) {
    if (states.includes("pending")) return "running";
  }
  if (states.includes("unknown")) return "unknown";
  return "pending";
};

export const resolveScanStageRows = (stages: AuditStageStatus[]): ScanStageRow[] => {
  const byId = stageById(stages);
  return SCAN_STAGE_ROW_IDS.map((id) => {
    const sources = ROW_SOURCE_STAGES[id].map((stageId) => byId.get(stageId)).filter(Boolean);
    const status = combineStates(sources as AuditStageStatus[]);
    const failing = (sources as AuditStageStatus[]).find((stage) => stage.status === "failed");
    return { id, status, reason: failing?.reason ?? null };
  });
};

/** The first row whose state is `failed`, which is the row the failure belongs to. */
export const findFailedStageRow = (rows: ScanStageRow[]): ScanStageRow | null =>
  rows.find((row) => row.status === "failed") ?? null;

const normalizeDomain = (value: string): string =>
  value
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/\/+$/, "");

/**
 * The most recent earlier scan for the same target, used as the comparison
 * baseline on the succeeded state. Returns null when the target has no earlier
 * scan, so the view says so instead of inventing a delta.
 */
export const findPreviousScan = (
  history: AuditHistoryItem[],
  current: { auditId: number | null; url: string; targetName: string }
): AuditHistoryItem | null => {
  const url = normalizeDomain(current.url);
  const name = current.targetName.trim().toLowerCase();
  if (!url && !name) return null;

  const matches = history.filter((entry) => {
    if (current.auditId !== null && entry.id === current.auditId) return false;
    if (url) {
      const entryUrl = normalizeDomain(entry.targetUrl || entry.url || "");
      if (entryUrl && entryUrl === url) return true;
    }
    if (name) {
      const entryName = (entry.targetName || "").trim().toLowerCase();
      if (entryName && entryName === name) return true;
    }
    return false;
  });

  if (matches.length === 0) return null;
  return matches.reduce((latest, entry) =>
    new Date(entry.createdAt).getTime() > new Date(latest.createdAt).getTime() ? entry : latest
  );
};

/**
 * The third stat of the approved succeeded view, AI visibility.
 *
 * It is the project's own measured figure, produced by the AI visibility
 * monitoring runs over the prompts the project tracks
 * (`ProjectVisibilityService.build_summary` -> `visibility_score`, served by
 * `GET /api/v1/projects/{id}/monitoring/visibility-summary`). It is the same
 * number the dashboard's "Does AI find you?" and the report page's third
 * figure show, so the surfaces agree. A scan produces no visibility
 * measurement of its own, which is why the stat names monitoring as its basis
 * and carries the measurement's own date.
 *
 * `delta` is the payload's `trend_delta`: the move between the two most recent
 * measured points of the same series, so it is a real comparison and not a
 * scan-to-scan one. It stays null when the series has only one point.
 */
export type ScanVisibilityStat =
  | {
      state: "measured";
      /** Whole percent of tracked answers the brand appeared in. */
      percent: number;
      /** Signed percentage-point move against the previous measured point, or null. */
      delta: number | null;
      measuredAt: string | null;
    }
  | { state: "unmeasured"; reason: "locked" | "no_run" };

/**
 * Null means there is nothing to state at all: no project behind the scan, or
 * the summary has not been read. The unmeasured states are the honest words
 * the rest of the product uses, never a 0 and never a dash standing in for a
 * number.
 */
export const resolveScanVisibilityStat = (
  summary: VisibilitySummaryResponse | null | undefined
): ScanVisibilityStat | null => {
  if (!summary) return null;
  if (summary.entitlements?.is_locked) return { state: "unmeasured", reason: "locked" };

  const score = summary.visibility_score;
  if (
    (summary.completed_checks ?? 0) <= 0 ||
    typeof score !== "number" ||
    !Number.isFinite(score)
  ) {
    return { state: "unmeasured", reason: "no_run" };
  }

  const trend = summary.trend_delta;
  return {
    state: "measured",
    percent: Math.round(score),
    delta: typeof trend === "number" && Number.isFinite(trend) ? Math.round(trend) : null,
    measuredAt: summary.last_updated_at ?? null,
  };
};

export type ScanDuration = { unit: "minutes" | "seconds"; count: number };

/**
 * Elapsed run time from the job's own timestamps. Null when either timestamp
 * is missing, so the succeeded line drops the duration rather than guessing.
 */
export const resolveScanDuration = (
  startedAt: string | null,
  completedAt: string | null
): ScanDuration | null => {
  if (!startedAt || !completedAt) return null;
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 90) return { unit: "seconds", count: Math.max(seconds, 1) };
  return { unit: "minutes", count: Math.round(seconds / 60) };
};

/** Whole days until the rolling allowance window frees its oldest scan. */
export const resolveResetInDays = (
  resetAt: string | null | undefined,
  now: Date = new Date()
): number | null => {
  if (!resetAt) return null;
  const reset = new Date(resetAt).getTime();
  if (Number.isNaN(reset)) return null;
  const days = Math.ceil((reset - now.getTime()) / 86_400_000);
  return days > 0 ? days : 0;
};
