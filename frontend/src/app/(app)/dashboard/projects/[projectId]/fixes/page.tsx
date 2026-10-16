"use client";

// Rebuilt against Qiko-Signal-MVP-TBR/mockup/Signal Fixes.html: breadcrumb
// bar, "Your action plan" pagehead, an About-impact alert, category + status
// segmented filters, ROI-ranked fix cards and the About-dismissing footer.
// Data: the deterministic Advisor plan (report.metadata.advisor) joined back
// to canonical recommendations.items[]; resolveActionImpact /
// resolveActionEffort decide whether a rating was measured at all, because
// the backend labels are silently defaulted (see reportAdapters). Dismiss
// posts that canonical action text plus the action's deterministic
// problem_code, when it has one, to recommendation-decisions.
// Approved elements with no source render as explicit unrated states or are
// omitted: page counts, and any numeric impact figure. Impact is categorical
// by product rule, so expected_score_impact is read only to decide the band
// and to name the moved pillar, never printed.
// The mockup's trailing backend-ticket marker on the impact note, and all of
// its demo rows, are annotations to the build team and must never render.
// page.test.tsx scans this file to keep them out.
// SIGV2-1211: the page opens on live work only. Done and dismissed actions are
// partitioned off before any filtering and folded into two accordions that are
// closed by default, each with its own count and its own way back out. Nothing
// is deleted to achieve that: a dismissal is a decision record the server
// upserts, so restoring one supersedes it, and reopening a completed action
// moves its board task rather than removing it.
import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Trans, useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/custom-auth";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { isAuditResult } from "@/types/auditResult";
import {
  getConsolidatedFixes,
  type CanonicalAuditReport,
  type ConsolidatedFix,
  type ScorePillar,
} from "@/lib/reportAdapters";
import { fixSourceLabelKeys } from "@/lib/fixSource";
import { resolveAdvisorPlanAccess } from "@/lib/advisorPlanAccess";
import { workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import {
  createProjectTask,
  fetchProjectTasks,
  updateProjectTask,
  type ProjectTaskBoard,
  type ProjectTaskItem,
  type ProjectTaskStatus,
} from "@/services/workspaceService";
import {
  fetchRecommendationDecisions,
  recordRecommendationDecision,
} from "@/services/learningsService";
import SignalCrumb from "@/components/signal/SignalCrumb";
import { SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import { cx } from "@/components/ui/utils";

// The approved filter vocabulary minus "Feature". The taxonomy is closed at
// exactly Technical / Content / Backlinks: the enrichment prompt constrains
// it (ai_engine.py, "category must be one of: Technical, Content,
// Backlinks"), audit_runner._to_canonical_suggestions maps anything else to
// null, and the Suggestion model pins the same Literal. "Feature" can
// therefore never match, and a filter that always returns nothing is worse
// than an absent one, so it is dropped and reported as a design-versus-
// taxonomy divergence. Backlinks renders under the approved "Authority"
// label: the design's only Authority row is a backlink-earning action, so
// the two words denote one class and the customer sees the approved one.
type CatFilter = "all" | "content" | "technical" | "authority";
const CAT_FILTERS: CatFilter[] = ["all", "content", "technical", "authority"];
type StatusFilter = "all" | "open" | "prog" | "done";
// SIGV2-1211: the status filter triages live work, so it offers only the
// states the active list can hold. "Done" is not one of them any more - done
// work lives in the Completed accordion - and a filter option that can never
// match anything is worse than an absent one, the same reason "Feature" is
// absent from the category row above. `"done"` stays in the type because
// `rowStatus` still reports it and the Done chip still renders it.
const STATUS_FILTERS: StatusFilter[] = ["all", "open", "prog"];

// Matches problem_codes.PROBLEM_CODE_KEY_PREFIX on the server.
const PROBLEM_CODE_KEY_PREFIX = "problem:";

const normalizeText = (value: string | null | undefined): string =>
  String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");

const displayCategory = (category: string | null | undefined): CatFilter | null => {
  const raw = normalizeText(category);
  if (raw === "content") return "content";
  if (raw === "technical") return "technical";
  if (raw === "backlinks") return "authority";
  return null;
};

const chipBase = "rounded-[6px] px-2 py-[3px] font-mono text-[10.5px] uppercase tracking-[0.04em]";
const chipEffCls = `${chipBase} bg-(--line-2) text-(--t-2)`;
const chipCatCls = `${chipBase} bg-(--purple-a10) text-(--purple)`;
const chipProgCls = `${chipBase} bg-(--warn-s) text-(--warn)`;
const chipDoneCls = `${chipBase} bg-(--good-s) text-(--good)`;
const chipDismissedCls = `${chipBase} bg-(--line-2) text-(--t-3)`;
const chipSourceCls = `${chipBase} border-0 bg-[#EEF1F6] text-(--t-3)`;
const chipUnratedCls = `${chipBase} border border-dashed border-(--line) text-(--t-3) normal-case`;

const segBtnCls =
  "cursor-pointer rounded-[6px] border-none px-3 py-1.5 font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-2)";
const segBtnOnCls = "bg-(--ink) text-white";
// Row actions match the Category/Status selected pill: solid ink primary,
// muted track secondary — so Mark done / Mark not started / Dismiss read as
// buttons, not plain text links on the white card.
const btnSmCls =
  "inline-flex h-[32px] min-w-[7.5rem] cursor-pointer items-center justify-center rounded-full border-0 bg-(--ink) px-3 font-(family-name:--body-font) text-[12.5px] font-semibold text-white transition-colors duration-150 hover:bg-black disabled:cursor-not-allowed disabled:opacity-50";
const btnSmGhostCls =
  "inline-flex h-[32px] min-w-[7.5rem] cursor-pointer items-center justify-center rounded-full border-0 bg-[#EEF1F6] px-3 font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) transition-colors duration-150 hover:bg-[#E2E6EE] disabled:cursor-not-allowed disabled:opacity-50";
const btnPrimaryCls =
  "inline-flex h-[38px] cursor-pointer items-center justify-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black";

// SIGV2-1193: a row is one entry of the single consolidated fix list, so this
// page and the Improve tabs can no longer disagree about how many fixes exist.
// It used to be an Advisor action joined to its canonical item here; that join
// now happens once, inside `getConsolidatedFixes`, along with the fold of the
// audit's own findings into the same rows.
type FixRow = {
  fix: ConsolidatedFix;
  task: ProjectTaskItem | null;
};

// Server-synced task rows carry a `source_recommendation_key` the server
// derives itself (resolve_task_recommendation_key in project_task_service.py):
// a task is an audit recommendation when its title, casefolded and whitespace
// normalized, matches a candidate in its source audit. The read side joins on
// that same normalized title across every text the row can be known by, which
// covers the task titles the sync path persists.
const matchTask = (fix: ConsolidatedFix, tasks: ProjectTaskItem[]) => {
  const keys = new Set([fix.title, fix.description, fix.actionText].map(normalizeText));
  keys.delete("");
  return tasks.find((task) => keys.has(normalizeText(task.title))) ?? null;
};

// The dismiss contract: the server stores `action_label` from the posted
// `action_text` and fingerprints it with sha256(text.strip().lower())
// (learnings_service.compute_action_fingerprint). attach_advisor_view
// fingerprints the canonical `action` of each suggestion, so the posted text
// must be that same canonical action or backend suppression silently misses.
// `actionText` is that canonical action when the row has one; a row that only
// an audit finding raised has none, and falls back to its title, which is then
// what the server stores as the label.
const dismissKey = (fix: ConsolidatedFix): string => fix.actionText ?? fix.title;

// SIGV2-1118 adds a second, durable key alongside that text: when a
// deterministic check raised the action it carries a `problem_code`, stored as
// `problem:<code>`. The text key only holds while the wording holds, and an LLM
// rewrites that wording on every audit. Both keys are checked, because
// decisions recorded before codes existed carry only the text key.

const problemCodeKey = (code: string | null | undefined): string | null =>
  code ? `${PROBLEM_CODE_KEY_PREFIX}${code}` : null;

/**
 * SIGV2-1211: one collapsed section of finished work. Closed by default, so
 * the page opens on what is still to do. The panel is conditionally rendered
 * rather than hidden with CSS: a closed section holds records a customer has
 * already dealt with, and keeping them out of the DOM keeps them out of
 * find-in-page and the screen-reader order too.
 */
function FixHistorySection({
  id,
  label,
  open,
  onToggle,
  children,
}: {
  id: string;
  label: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-(--r-md) border-0 bg-white">
      <h2 className="m-0">
        <button
          type="button"
          id={`fix-history-${id}-trigger`}
          data-testid={`fix-history-${id}-trigger`}
          aria-expanded={open}
          aria-controls={`fix-history-${id}-panel`}
          onClick={onToggle}
          className="flex w-full cursor-pointer items-center gap-2 rounded-(--r-md) border-none bg-transparent px-[18px] py-3.5 font-(family-name:--body-font) text-[13px] font-semibold text-(--t-1) hover:bg-(--line-2) ltr:text-left rtl:text-right"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
            className={cx(
              "h-3.5 w-3.5 flex-none text-(--t-3) transition-transform",
              open && "rotate-180"
            )}
          >
            <path d="M6 9l6 6 6-6" strokeLinecap="round" />
          </svg>
          {label}
        </button>
      </h2>
      {open ? (
        <div
          id={`fix-history-${id}-panel`}
          data-testid={`fix-history-${id}-panel`}
          role="region"
          aria-labelledby={`fix-history-${id}-trigger`}
          className="border-t border-t-(--line-2) px-[18px] py-3.5"
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

export default function ProjectFixesPage() {
  const { t } = useTranslation();
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const base = `/dashboard/projects/${projectId}`;

  const { project, latestAudit, loading, error } = useProjectLatestAudit(projectId, {
    includeFullReport: true,
  });
  const { getToken, isSignedIn } = useAuth();

  const [board, setBoard] = useState<ProjectTaskBoard | null>(null);
  const [boardError, setBoardError] = useState<string | null>(null);
  const [catFilter, setCatFilter] = useState<CatFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [alertDismissed, setAlertDismissed] = useState(false);
  // Optimistic/persisted view state: dismissed action texts and pending
  // mutations. Persisted decisions are fetched on load because the persisted
  // audit report carries the unfiltered advisor plan; a dismissed fix would
  // otherwise reappear on reload.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // Dismissed deterministic identities, held separately from the text keys
  // above so a reworded fix is still recognised as dismissed.
  const [dismissedCodes, setDismissedCodes] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // SIGV2-1211: finished work is folded away, closed on load.
  const [completedOpen, setCompletedOpen] = useState(false);
  const [dismissedOpen, setDismissedOpen] = useState(false);

  const { setHeader } = useWorkspacePageHeader();
  const topCrumb = useMemo(
    () => (
      <SignalCrumb
        items={[
          { label: t("signalFixes.plan.crumbHome"), href: base },
          { label: t("signalFixes.plan.crumbCurrent") },
        ]}
      />
    ),
    [t, base]
  );
  useEffect(() => {
    setHeader({ crumb: topCrumb });
    return () => setHeader(null);
  }, [setHeader, topCrumb]);

  // SIGV2-1134: the same served entitlement the dashboard's preview card uses.
  // This used to resolve off the offline capability table keyed on the signed-in
  // user's plan string, which is a frontend copy of the plan matrix and not what
  // the backend served for this project.
  const advisorPlan = resolveAdvisorPlanAccess(project);
  const canPlan = advisorPlan.allowed;

  const authHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...workspaceHeaders() };
  }, [getToken]);

  const loadBoard = useCallback(async () => {
    if (!projectId || !isSignedIn) return;
    try {
      const headers = await authHeaders();
      const next = await fetchProjectTasks(projectId, headers);
      setBoard(next);
      setBoardError(null);
    } catch (e) {
      setBoard(null);
      setBoardError(e instanceof Error ? e.message : String(e));
    }
  }, [projectId, isSignedIn, authHeaders]);

  const loadDecisions = useCallback(async () => {
    if (!projectId || !isSignedIn) return;
    try {
      const headers = await authHeaders();
      const decisions = await fetchRecommendationDecisions(projectId, headers);
      setDismissed((prev) => {
        const next = new Set(prev);
        for (const entry of decisions) {
          if (entry.decision === "dismissed" && entry.action_label) {
            next.add(normalizeText(entry.action_label));
          }
        }
        return next;
      });
      setDismissedCodes((prev) => {
        const next = new Set(prev);
        for (const entry of decisions) {
          if (
            entry.decision === "dismissed" &&
            entry.action_fingerprint?.startsWith(PROBLEM_CODE_KEY_PREFIX)
          ) {
            next.add(entry.action_fingerprint);
          }
        }
        return next;
      });
    } catch {
      // Decisions are best-effort; the board error path covers task failures.
    }
  }, [projectId, isSignedIn, authHeaders]);

  useEffect(() => {
    void loadBoard();
    void loadDecisions();
  }, [loadBoard, loadDecisions]);

  const report = useMemo(() => {
    const raw = latestAudit?.full_report;
    return isAuditResult(raw) ? (raw as unknown as CanonicalAuditReport) : null;
  }, [latestAudit]);
  // SIGV2-1193: the one consolidated list. The Advisor plan, the canonical
  // recommendation items and the audit's own score-breakdown findings are
  // joined on the deterministic `problem_code` inside `getConsolidatedFixes`,
  // which also keeps the SIGV2-1096 fallback (a degraded run grounds nothing,
  // the plan comes back empty, and the candidates are listed unrated rather
  // than the page claiming no check ran).
  const fixes = useMemo(() => (report ? getConsolidatedFixes(report) : []), [report]);

  const tasks = useMemo(() => board?.tasks ?? [], [board]);
  const isDismissed = useCallback(
    (row: FixRow): boolean => {
      const code = problemCodeKey(row.fix.problemCode);
      if (code && dismissedCodes.has(code)) return true;
      return dismissed.has(normalizeText(dismissKey(row.fix)));
    },
    [dismissed, dismissedCodes]
  );
  const rows = useMemo<FixRow[]>(
    () => fixes.map((fix) => ({ fix, task: matchTask(fix, tasks) })),
    [fixes, tasks]
  );

  // SIGV2-1211: partition before filtering or rendering. Dismissed rows used
  // to be dropped from `rows` here, which left nothing to list them from, so
  // they are retained and routed to their own section instead. Nothing is
  // deleted to make that work: a dismissal is a decision record, and
  // restoring one supersedes it rather than removing it.
  const { activeRows, completedRows, dismissedRows } = useMemo(() => {
    const active: FixRow[] = [];
    const completed: FixRow[] = [];
    const dismissedList: FixRow[] = [];
    for (const row of rows) {
      if (isDismissed(row)) dismissedList.push(row);
      else if (row.task?.status === "done") completed.push(row);
      else active.push(row);
    }
    return { activeRows: active, completedRows: completed, dismissedRows: dismissedList };
  }, [rows, isDismissed]);

  // Done recommendations that no longer appear in the current plan still have
  // a board record, so they are listed alongside the matched done rows rather
  // than dropped. The status filter no longer gates them: it scopes the active
  // list only.
  const doneOrphans = useMemo(() => {
    const matched = new Set(rows.map((r) => r.task?.id).filter(Boolean));
    return tasks.filter(
      (task) =>
        task.status === "done" && task.origin === "audit_recommendation" && !matched.has(task.id)
    );
  }, [rows, tasks]);

  const rowStatus = (row: FixRow): StatusFilter =>
    row.task?.status === "done" ? "done" : row.task?.status === "in_progress" ? "prog" : "open";

  const visibleRows = activeRows.filter((row) => {
    const cat = displayCategory(row.fix.category);
    const catOk = catFilter === "all" || cat === catFilter;
    const stOk = statusFilter === "all" || rowStatus(row) === statusFilter;
    return catOk && stOk;
  });
  const completedCount = completedRows.length + doneOrphans.length;

  const setPendingOn = (id: string, on: boolean) =>
    setPending((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const markDone = async (row: FixRow) => {
    const id = row.fix.id;
    setPendingOn(id, true);
    setActionError(null);
    const previous = board;
    // Optimistic: reflect done state immediately.
    if (row.task) {
      setBoard((b) =>
        b
          ? {
              ...b,
              tasks: b.tasks.map((task) =>
                task.id === row.task!.id ? { ...task, status: "done" as ProjectTaskStatus } : task
              ),
            }
          : b
      );
    } else {
      // The server derives the recommendation key and origin from
      // source_audit_id + title, so the optimistic row only needs to look
      // like the persisted one until the board refetches.
      const optimistic: ProjectTaskItem = {
        id: -Date.now(),
        project_id: Number(projectId),
        title: row.fix.title,
        description: null,
        status: "done",
        priority: "medium",
        origin: "audit_recommendation",
        category: row.fix.category || "general",
        source_audit_id: latestAudit?.id ?? null,
        source_recommendation_key: null,
        assigned_to_user_id: null,
        assignee: null,
        due_date: null,
        resolved_at: new Date().toISOString(),
        verified_at: null,
        verification_audit_id: null,
        resolution_source: "manual",
        sort_order: 0,
        created_at: null,
        updated_at: null,
      };
      setBoard((b) => (b ? { ...b, tasks: [...b.tasks, optimistic] } : b));
    }
    try {
      const headers = await authHeaders();
      if (row.task) {
        await updateProjectTask(projectId, row.task.id, { status: "done" }, headers);
      } else {
        await createProjectTask(
          projectId,
          {
            title: row.fix.title,
            status: "done",
            category: row.fix.category || "general",
            source_audit_id: latestAudit?.id ?? null,
          },
          headers
        );
      }
      await loadBoard();
      setNotice(t("signalFixes.plan.markedDone"));
    } catch (e) {
      setBoard(previous);
      setActionError(
        e instanceof Error && e.message ? e.message : t("signalFixes.plan.actionFailed")
      );
    } finally {
      setPendingOn(id, false);
    }
  };

  const dismiss = async (row: FixRow) => {
    const id = row.fix.id;
    setPendingOn(id, true);
    setActionError(null);
    const text = dismissKey(row.fix);
    const dismissedKey = normalizeText(text);
    const code = row.fix.problemCode ?? null;
    const codeKey = problemCodeKey(code);
    setDismissed((prev) => new Set(prev).add(dismissedKey));
    if (codeKey) setDismissedCodes((prev) => new Set(prev).add(codeKey));
    try {
      const headers = await authHeaders();
      await recordRecommendationDecision(
        projectId,
        { action_text: text, problem_code: code, decision: "dismissed" },
        headers
      );
      setNotice(t("signalFixes.plan.dismissed"));
    } catch (e) {
      setDismissed((prev) => {
        const next = new Set(prev);
        next.delete(dismissedKey);
        return next;
      });
      if (codeKey)
        setDismissedCodes((prev) => {
          const next = new Set(prev);
          next.delete(codeKey);
          return next;
        });
      setActionError(
        e instanceof Error && e.message ? e.message : t("signalFixes.plan.actionFailed")
      );
    } finally {
      setPendingOn(id, false);
    }
  };

  // SIGV2-1211: the way back out of the Completed section. The board record is
  // moved, never deleted, so the history of the task survives; "done" here is
  // a status the customer set, not a measurement, and they are allowed to
  // change their mind. A failed write rolls the row back so a retry is in
  // front of them rather than lost.
  const reopen = async (task: ProjectTaskItem, pendingId: string) => {
    setPendingOn(pendingId, true);
    setActionError(null);
    const previous = board;
    setBoard((b) =>
      b
        ? {
            ...b,
            tasks: b.tasks.map((entry) =>
              entry.id === task.id ? { ...entry, status: "todo" as ProjectTaskStatus } : entry
            ),
          }
        : b
    );
    try {
      const headers = await authHeaders();
      await updateProjectTask(projectId, task.id, { status: "todo" }, headers);
      await loadBoard();
      setNotice(t("signalFixes.plan.history.reopened"));
    } catch (e) {
      setBoard(previous);
      setActionError(
        e instanceof Error && e.message ? e.message : t("signalFixes.plan.actionFailed")
      );
    } finally {
      setPendingOn(pendingId, false);
    }
  };

  // The way back out of the Dismissed section. The decision row is an upsert
  // on (project, fingerprint) server-side, so recording "accepted" supersedes
  // the dismissal in place; nothing is deleted and the audit trail holds.
  const restore = async (row: FixRow) => {
    const id = row.fix.id;
    setPendingOn(id, true);
    setActionError(null);
    const text = dismissKey(row.fix);
    const dismissedKey = normalizeText(text);
    const code = row.fix.problemCode ?? null;
    const codeKey = problemCodeKey(code);
    setDismissed((prev) => {
      const next = new Set(prev);
      next.delete(dismissedKey);
      return next;
    });
    if (codeKey)
      setDismissedCodes((prev) => {
        const next = new Set(prev);
        next.delete(codeKey);
        return next;
      });
    try {
      const headers = await authHeaders();
      await recordRecommendationDecision(
        projectId,
        { action_text: text, problem_code: code, decision: "accepted" },
        headers
      );
      setNotice(t("signalFixes.plan.history.restored"));
    } catch (e) {
      setDismissed((prev) => new Set(prev).add(dismissedKey));
      if (codeKey) setDismissedCodes((prev) => new Set(prev).add(codeKey));
      setActionError(
        e instanceof Error && e.message ? e.message : t("signalFixes.plan.actionFailed")
      );
    } finally {
      setPendingOn(id, false);
    }
  };

  const canEdit = board?.can_edit !== false;
  const actionsDisabled = !canEdit;

  // One card shape for all three lists, so a folded row reads as the same
  // record it was before it was folded. Only the trailing controls differ:
  // active work can be finished or dismissed, finished work can be taken back.
  const renderRow = (row: FixRow, mode: "active" | "completed" | "dismissed") => {
    const { fix } = row;
    const done = rowStatus(row) === "done";
    const prog = rowStatus(row) === "prog";
    const cat = displayCategory(fix.category);
    const pillars = fix.pillars;
    const effort = fix.effortLevel;
    const impact = fix.impactLevel;
    const groundedBy = fix.groundedBy;
    const isPending = pending.has(fix.id);
    return (
      <div
        key={fix.id}
        data-testid={`fix-${fix.id}`}
        className={cx(
          "flex items-start gap-4 rounded-(--r-md) border-0 bg-white px-[18px] py-4",
          "mt-2.5 first:mt-0",
          mode !== "active" && "opacity-[.62]"
        )}
      >
        <span className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-[8px] border-0 bg-[#EEF1F6] font-mono text-[11px] text-(--t-2)">
          {fix.rank}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="m-0 mb-1 font-(family-name:--disp) text-[14px] font-bold">{fix.title}</h3>
          <p className="m-0 mb-2 text-[12.5px] leading-[1.55] text-(--t-2)">
            {fix.description || fix.title}
            {pillars.length > 0 ? (
              <>
                {" "}
                <Trans
                  i18nKey="signalFixes.plan.movesPillars"
                  values={{
                    pillars: pillars
                      .map((p: ScorePillar) => t(`signalFixes.plan.pillar.${p}`))
                      .join(` ${t("signalFixes.plan.and")} `),
                  }}
                  components={{ b: <b /> }}
                />
              </>
            ) : null}
            {groundedBy.length > 0 ? (
              <>
                {" "}
                <Link
                  href={`/dashboard/audit/${latestAudit?.id ?? ""}`}
                  className="font-semibold text-(--brand) hover:underline"
                  title={groundedBy.join(", ")}
                >
                  {t("signalFixes.plan.evidence", { count: groundedBy.length })}
                </Link>
              </>
            ) : null}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {/* SIGV2-1193: which list raised this row. One ordered list now,
                but the customer keeps the answer SIGV2-1175 gave them about
                where a fix came from. */}
            {fixSourceLabelKeys(fix.sources).map((key) => (
              <span key={key} className={chipSourceCls}>
                {t(key)}
              </span>
            ))}
            {cat ? (
              <span className={chipCatCls}>
                {t("signalFixes.plan.catChip", { cat: t(`signalFixes.plan.cat.${cat}`) })}
              </span>
            ) : (
              <span className={chipUnratedCls} title={t("signalFixes.plan.unratedHint")}>
                {t("signalFixes.plan.catUnrated")}
              </span>
            )}
            {effort.measured ? (
              <span className={chipEffCls}>
                {t("signalFixes.plan.effortRated", {
                  level: t(`signalFixes.plan.level.${effort.level}`),
                })}
              </span>
            ) : (
              <span className={chipUnratedCls} title={t("signalFixes.plan.unratedHint")}>
                {t("signalFixes.plan.effortUnrated")}
              </span>
            )}
            {impact.measured ? (
              <span className={chipEffCls}>
                {t("signalFixes.plan.impactRated", {
                  level: t(`signalFixes.plan.level.${impact.level}`),
                })}
              </span>
            ) : (
              <span className={chipUnratedCls} title={t("signalFixes.plan.unratedHint")}>
                {t("signalFixes.plan.impactUnrated")}
              </span>
            )}
            {mode === "dismissed" ? (
              <span className={chipDismissedCls}>
                {t("signalFixes.plan.history.dismissedChip")}
              </span>
            ) : null}
            {mode !== "dismissed" && prog ? (
              <span className={chipProgCls}>{t("signalFixes.plan.st.prog")}</span>
            ) : null}
            {mode !== "dismissed" && done ? (
              <span className={chipDoneCls}>{t("signalFixes.plan.st.done")}</span>
            ) : null}
          </div>
        </div>
        {mode === "active" ? (
          <div className="flex flex-none flex-col items-stretch gap-2">
            <button
              type="button"
              className={btnSmCls}
              disabled={actionsDisabled || isPending}
              title={actionsDisabled ? t("signalFixes.plan.readOnly") : undefined}
              onClick={() => void markDone(row)}
            >
              {t("signalFixes.plan.markDone")}
            </button>
            <button
              type="button"
              className={btnSmGhostCls}
              disabled={actionsDisabled || isPending}
              title={actionsDisabled ? t("signalFixes.plan.readOnly") : undefined}
              onClick={() => void dismiss(row)}
            >
              {t("signalFixes.plan.dismiss")}
            </button>
          </div>
        ) : null}
        {mode === "completed" && row.task ? (
          <div className="flex flex-none flex-col items-stretch gap-2">
            <button
              type="button"
              className={btnSmCls}
              disabled={actionsDisabled || isPending}
              title={actionsDisabled ? t("signalFixes.plan.readOnly") : undefined}
              onClick={() => void reopen(row.task!, fix.id)}
            >
              {t("signalFixes.plan.history.reopen")}
            </button>
          </div>
        ) : null}
        {mode === "dismissed" ? (
          <div className="flex flex-none flex-col items-stretch gap-2">
            <button
              type="button"
              className={btnSmCls}
              disabled={actionsDisabled || isPending}
              title={actionsDisabled ? t("signalFixes.plan.readOnly") : undefined}
              onClick={() => void restore(row)}
            >
              {t("signalFixes.plan.history.restore")}
            </button>
          </div>
        ) : null}
      </div>
    );
  };

  if (loading) {
    return (
      <div role="status" aria-label={t("signalFixes.loading")} className="flex flex-col gap-5">
        <SkelPagehead />
        <SkelCard />
        <SkelCard />
        <SkelCard />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-3.5 flex flex-col items-center gap-3 rounded-[22px] border-0 bg-white px-6 py-[22px] text-center text-[13px] text-(--t-2)">
        <span>{t("signalFixes.plan.loadFailed")}</span>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-[22px]">
      {/* signal-MVP `.pagehead` */}
      <div className="flex items-center gap-3.5">
        <div className="flex h-[46px] w-[46px] flex-none items-center justify-center rounded-[13px] bg-(--purple-a10) text-(--purple)">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.9}
            className="h-[23px] w-[23px]"
          >
            <path d="M13 2L3 14h7l-1 8 10-12h-7z" />
          </svg>
        </div>
        <div>
          <h1 className="m-0 font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em]">
            {t("signalFixes.plan.title")}
          </h1>
          <div className="mt-[3px] max-w-[640px] text-[13px] leading-[1.5] text-(--t-2)">
            {t("signalFixes.plan.subtitle")}
          </div>
        </div>
      </div>

      {/* signal-MVP `.alert.info` */}
      {!alertDismissed && (
        <div
          className="relative flex gap-[11px] rounded-(--r-md) border-0 bg-[color-mix(in_srgb,var(--blue)_5%,transparent)] px-[15px] py-[13px] text-[13px] leading-[1.5] text-(--t-2)"
          role="note"
        >
          <svg
            className="mt-px h-[17px] w-[17px] flex-none text-(--blue)"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
          >
            <circle cx="12" cy="12" r="9" />
            <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
          </svg>
          <div className="min-w-0 flex-1">
            <span className="mb-0.5 block text-[13.5px] font-bold text-(--t-1)">
              {t("signalFixes.plan.alertTitle")}
            </span>
            {t("signalFixes.plan.alertBody")}
          </div>
          <button
            type="button"
            aria-label={t("signalFixes.plan.alertDismiss")}
            onClick={() => setAlertDismissed(true)}
            className="absolute top-[9px] flex cursor-pointer items-center justify-center rounded-[6px] border-none bg-transparent p-[3px] text-(--t-3) hover:bg-(--line-2) hover:text-(--t-1) max-md:min-h-11 max-md:min-w-11 ltr:right-[9px] rtl:left-[9px]"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              className="h-[13px] w-[13px]"
            >
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}

      {!canPlan ? (
        /* Plan gate: the served `advisor_recommendations` entitlement, which
           the backend builds from has_advisor_recommendations (False on the
           first tier, True from plan_standard up). The plan named here and the
           billing link both come from that same payload, so this card and the
           dashboard's preview lock always name one plan. */
        <div className="flex justify-center">
          <div className="w-full max-w-[420px] rounded-[22px] border-0 bg-white px-[30px] py-7 text-center shadow-[0_24px_60px_-12px_rgba(12,15,22,0.12)]">
            <div className="text-[10.5px] uppercase tracking-[0.14em] text-(--purple)">
              {advisorPlan.requiredPlan ?? t("signalFixes.plan.gateEyebrow")}
            </div>
            <h3 className="mt-2 mb-1.5 font-(family-name:--disp) text-[18px] font-extrabold tracking-[-0.02em]">
              {t("signalFixes.plan.gateTitle")}
            </h3>
            <p className="mb-4 text-[13px] leading-[1.5] text-(--t-2)">
              {advisorPlan.requiredPlan
                ? t("signalFixes.plan.gateBodyPlan", { plan: advisorPlan.requiredPlan })
                : t("signalFixes.plan.gateBody")}
            </p>
            <Link href={advisorPlan.upgradeHref} className={`${btnPrimaryCls} w-full`}>
              {advisorPlan.requiredPlan
                ? t("signalFixes.plan.gateCtaPlan", { plan: advisorPlan.requiredPlan })
                : t("signalFixes.plan.gateCta")}
            </Link>
          </div>
        </div>
      ) : (
        <>
          {/* signal-MVP filter card: two `.seg` groups */}
          <div className="flex flex-wrap items-center gap-3.5 rounded-[22px] border-0 bg-white px-[18px] py-3.5">
            <span className="m-0 text-[12px] text-(--t-3)">{t("signalFixes.plan.filterCat")}</span>
            <div className="inline-flex gap-[2px] rounded-[9px] border-0 bg-[#EEF1F6] p-[3px] ltr:[direction:ltr]">
              {CAT_FILTERS.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  aria-pressed={catFilter === cat}
                  className={cx(segBtnCls, catFilter === cat && segBtnOnCls)}
                  onClick={() => setCatFilter(cat)}
                >
                  {t(`signalFixes.plan.cat.${cat}`)}
                </button>
              ))}
            </div>
            <span className="m-0 text-[12px] text-(--t-3) ltr:ml-2 rtl:mr-2">
              {t("signalFixes.plan.filterStatus")}
            </span>
            <div className="inline-flex gap-[2px] rounded-[9px] border-0 bg-[#EEF1F6] p-[3px] ltr:[direction:ltr]">
              {STATUS_FILTERS.map((st) => (
                <button
                  key={st}
                  type="button"
                  aria-pressed={statusFilter === st}
                  className={cx(segBtnCls, statusFilter === st && segBtnOnCls)}
                  onClick={() => setStatusFilter(st)}
                >
                  {t(`signalFixes.plan.st.${st}`)}
                </button>
              ))}
            </div>
          </div>

          {boardError ? (
            <SignalAlert tone="warning" title={t("alerts.warningTitle")}>
              {t("signalFixes.plan.boardUnavailable")}
            </SignalAlert>
          ) : null}
          {actionError ? (
            <SignalAlert tone="danger" title={t("alerts.errorTitle")}>
              {actionError}
            </SignalAlert>
          ) : null}
          {notice ? (
            <SignalAlert tone="success" title={t("alerts.successTitle")}>
              {notice}
            </SignalAlert>
          ) : null}

          {/* SIGV2-1175: this list is Advisor recommendations, a different
              data set from the Improve tab's audit findings, so the subtitle
              names the source and this line states the count actually
              rendered. SIGV2-1211 scopes it to the active list, which is what
              this part of the page renders; finished work states its own count
              on its own section. The two can never silently disagree. */}
          <p className="m-0 text-[12px] text-(--t-3)">
            {t("signalFixes.plan.count", { count: visibleRows.length })}
          </p>

          {/* signal-MVP `#fx-list` */}
          <div>
            {visibleRows.length === 0 ? (
              <div className="mt-1 flex flex-col items-center gap-2 rounded-(--r-md) border-0 bg-white px-6 py-[30px] text-center text-[13px] text-(--t-2)">
                <span>
                  {activeRows.length > 0
                    ? t("signalFixes.plan.emptyFiltered")
                    : rows.length > 0
                      ? /* Every action is folded away, which is not the same
                           claim as "a filter hid them". */
                        t("signalFixes.plan.emptyHistoryOnly")
                      : latestAudit
                        ? t("signalFixes.plan.emptyAfterScan")
                        : t("signalFixes.plan.emptyPlan")}
                </span>
              </div>
            ) : (
              visibleRows.map((row) => renderRow(row, "active"))
            )}
          </div>

          {/* SIGV2-1211: finished work, folded and closed by default. Each
              section states its own count, and each row keeps its way back
              out, because none of this is deleted. */}
          {completedCount > 0 ? (
            <FixHistorySection
              id="completed"
              label={t("signalFixes.plan.history.completed", { count: completedCount })}
              open={completedOpen}
              onToggle={() => setCompletedOpen((open) => !open)}
            >
              {completedRows.map((row) => renderRow(row, "completed"))}
              {/* Done records still on the board after they left the plan.
                  They have no advisor action to rebuild a card from, so they
                  render as the record they are. */}
              {doneOrphans.map((task) => (
                <div
                  key={`done-${task.id}`}
                  data-testid={`fix-done-${task.id}`}
                  className="mt-2.5 flex items-start gap-4 rounded-(--r-md) border-0 bg-white px-[18px] py-4 opacity-[.62] first:mt-0"
                >
                  <span className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-[8px] border-0 bg-[#EEF1F6] font-mono text-[11px] text-(--t-2)">
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      className="h-3 w-3"
                    >
                      <path d="M5 13l4 4L19 7" strokeLinecap="round" />
                    </svg>
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="m-0 mb-1 font-(family-name:--disp) text-[14px] font-bold">
                      {task.title}
                    </h3>
                    <p className="m-0 mb-2 text-[12.5px] leading-[1.55] text-(--t-2)">
                      {t("signalFixes.plan.doneRecord")}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {displayCategory(task.category) ? (
                        <span className={chipCatCls}>
                          {t("signalFixes.plan.catChip", {
                            cat: t(`signalFixes.plan.cat.${displayCategory(task.category)}`),
                          })}
                        </span>
                      ) : null}
                      <span className={chipDoneCls}>{t("signalFixes.plan.st.done")}</span>
                    </div>
                  </div>
                  <div className="flex flex-none flex-col gap-1.5">
                    <button
                      type="button"
                      className={btnSmCls}
                      disabled={actionsDisabled || pending.has(`done-${task.id}`)}
                      title={actionsDisabled ? t("signalFixes.plan.readOnly") : undefined}
                      onClick={() => void reopen(task, `done-${task.id}`)}
                    >
                      {t("signalFixes.plan.history.reopen")}
                    </button>
                  </div>
                </div>
              ))}
            </FixHistorySection>
          ) : null}

          {dismissedRows.length > 0 ? (
            <FixHistorySection
              id="dismissed"
              label={t("signalFixes.plan.history.dismissed", { count: dismissedRows.length })}
              open={dismissedOpen}
              onToggle={() => setDismissedOpen((open) => !open)}
            >
              {dismissedRows.map((row) => renderRow(row, "dismissed"))}
            </FixHistorySection>
          ) : null}

          {/* signal-MVP `.card.sblock` About dismissing */}
          <div className="rounded-[22px] border-0 bg-white px-[22px] py-5">
            <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold">
              {t("signalFixes.plan.dismissTitle")}
            </h3>
            <div className="text-[12.5px] text-(--t-3)">
              <Trans i18nKey="signalFixes.plan.dismissBody" components={{ b: <b /> }} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
