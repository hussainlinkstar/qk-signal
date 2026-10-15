"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth/custom-auth";
import AuditAnnotationThread from "@/components/dashboard/AuditAnnotationThread";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { GlassCard } from "@/components/ui/GlassComponents";
import GeoIcon from "@/components/ui/GeoIcon";
import Button from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  ShieldCheck,
  Activity,
  Search,
  Sparkles,
  Filter,
  TrendingUp,
  Lightbulb,
  ArrowRight,
  MessageSquareMore,
  CheckCircle2,
  HelpCircle,
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { fetchAuditAnnotations } from "@/services/annotationService";
import {
  fetchProjectTasks,
  updateProjectTask,
  type ProjectTaskBoard,
  type ProjectTaskItem,
} from "@/services/workspaceService";
import { extractAuditAnnotationTargets } from "@/lib/auditAnnotationTargets";
import {
  getConsolidatedFixes,
  filterBrandOnlyRecommendations,
  type ConsolidatedFix,
} from "@/lib/reportAdapters";
import { fixSourceLabelKeys } from "@/lib/fixSource";
import { normalizeReportWithDiagnostics } from "@/lib/auditWorkspaceUtils";
import { getIntegrityStatusSnapshot } from "@/lib/integrityStatus";
import { useJiraExportTracker } from "@/hooks/useJiraExportTracker";
import { buildAuditRecordResponse } from "@/lib/projectAuditFeature";

type RecommendationFilter = "all" | "seo" | "aeo" | "geo";

const RECOMMENDATIONS_PER_PAGE = 5;

type RecommendationsHubClientProps = {
  projectId?: string | number | null;
  initialFilter?: RecommendationFilter;
  lockFilter?: boolean;
};

const PILLAR_ORDER = ["SEO", "AEO", "GEO"] as const;

const normalizeMatchText = (value: string | null | undefined): string =>
  String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");

const normalizeMatchTextLoose = (value: string | null | undefined): string =>
  normalizeMatchText(value)
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

export default function RecommendationsHubClient({
  projectId: propProjectId,
  initialFilter = "all",
  lockFilter = false,
}: RecommendationsHubClientProps) {
  const router = useRouter();
  const { t } = useTranslation();
  const { getToken, isSignedIn } = useAuth();
  const params = useParams<{ projectId: string }>();
  const projectId = propProjectId || params?.projectId || "";
  const { getTrackedExport } = useJiraExportTracker(projectId);

  const [filter, setFilter] = useState<RecommendationFilter>(initialFilter);
  const [currentPage, setCurrentPage] = useState(0);
  const [annotationCounts, setAnnotationCounts] = useState<Record<string, number>>({});
  const [expandedAnnotationPath, setExpandedAnnotationPath] = useState<string | null>(null);
  const [diagnosticsExpanded, setDiagnosticsExpanded] = useState(false);

  const [taskBoard, setTaskBoard] = useState<ProjectTaskBoard | null>(null);
  const [boardFailed, setBoardFailed] = useState(false);
  const [optimisticStatus, setOptimisticStatus] = useState<Record<string, "done" | "todo">>({});
  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set());
  const [cardErrors, setCardErrors] = useState<Set<string>>(new Set());

  const { latestAudit, loading: isLoading } = useProjectLatestAudit(String(projectId));
  const normalizedAudit = useMemo(() => {
    if (!latestAudit) {
      return null;
    }
    return normalizeReportWithDiagnostics(buildAuditRecordResponse(latestAudit), latestAudit.url);
  }, [latestAudit]);

  const integritySnapshot = useMemo(() => {
    if (!normalizedAudit?.report) return null;
    return getIntegrityStatusSnapshot(normalizedAudit.report);
  }, [normalizedAudit?.report]);

  const allFilteredRecommendations = useMemo(() => {
    if (!normalizedAudit?.report) return [];

    let normalized = getConsolidatedFixes(normalizedAudit.report);

    // Filter out website-specific recommendations for brand-only audits
    const report = normalizedAudit.report as Record<string, any>;
    const targetType = report.target?.type || report.audit_target_type;
    const targetUrl = report.target?.url || report.site?.url || report.url;
    if (targetType === "brand" && !targetUrl) {
      normalized = filterBrandOnlyRecommendations(normalized);
    }

    if (filter === "all") return normalized;
    return normalized.filter((rec) => {
      const cat = rec.category.toLowerCase();
      const engines = rec.engines;

      if (filter === "seo") {
        return engines.includes("SEO") || cat.includes("seo") || cat.includes("technical");
      }
      if (filter === "aeo") {
        return (
          engines.includes("AEO") ||
          cat.includes("aeo") ||
          cat.includes("answer") ||
          cat.includes("content")
        );
      }
      if (filter === "geo") {
        return (
          engines.includes("GEO") ||
          cat.includes("geo") ||
          cat.includes("citation") ||
          cat.includes("generative")
        );
      }
      return cat === filter;
    });
  }, [filter, normalizedAudit?.report]);

  const annotationTargetsByTitle = useMemo(() => {
    const report = (latestAudit?.full_report || null) as Record<string, unknown> | null;
    const targets = extractAuditAnnotationTargets(report);
    return new Map(targets.map((target) => [target.title.toLowerCase(), target]));
  }, [latestAudit?.full_report]);

  useEffect(() => {
    const loadAnnotationCounts = async () => {
      if (!latestAudit?.id || !isSignedIn) {
        setAnnotationCounts({});
        return;
      }
      try {
        const token = await getToken();
        if (!token) {
          setAnnotationCounts({});
          return;
        }
        const response = await fetchAuditAnnotations(
          latestAudit.id,
          { Authorization: `Bearer ${token}` },
          { page: 1, perPage: 100 }
        );
        const counts: Record<string, number> = {};
        response.items.forEach((item) => {
          const key = item.section_path || item.source_recommendation_key || "";
          if (!key) {
            return;
          }
          counts[key] = (counts[key] || 0) + 1 + item.replies.length;
        });
        setAnnotationCounts(counts);
      } catch {
        setAnnotationCounts({});
      }
    };

    void loadAnnotationCounts();
  }, [getToken, isSignedIn, latestAudit?.id]);

  const loadTaskBoard = React.useCallback(async (): Promise<ProjectTaskBoard> => {
    if (!isSignedIn || !projectId) {
      throw new Error("not signed in");
    }
    const token = await getToken();
    if (!token) {
      throw new Error("not signed in");
    }
    const board = await fetchProjectTasks(projectId, { Authorization: `Bearer ${token}` });
    setTaskBoard(board);
    setBoardFailed(false);
    return board;
  }, [getToken, isSignedIn, projectId]);

  useEffect(() => {
    setTaskBoard(null);
    setBoardFailed(false);
    setOptimisticStatus({});
    setPendingKeys(new Set());
    setCardErrors(new Set());
    if (isSignedIn && projectId) {
      loadTaskBoard().catch(() => setBoardFailed(true));
    }
  }, [isSignedIn, projectId, latestAudit?.id, loadTaskBoard]);

  const taskForRecommendation = React.useCallback(
    (rec: ConsolidatedFix): ProjectTaskItem | undefined => {
      if (!taskBoard) {
        return undefined;
      }
      const recTitle = normalizeMatchText(rec.title);
      const recTitleLoose = normalizeMatchTextLoose(rec.title);
      const recCategory = normalizeMatchText(rec.category);
      let best: ProjectTaskItem | undefined;
      let bestScore = 0;
      let tied = false;
      for (const task of taskBoard.tasks) {
        if (task.origin !== "audit_recommendation") {
          continue;
        }
        const taskTitle = normalizeMatchText(task.title);
        const sameCategory = normalizeMatchText(task.category) === recCategory;
        let score = 0;
        if (taskTitle === recTitle) {
          score = sameCategory ? 3 : 2;
        } else if (normalizeMatchTextLoose(task.title) === recTitleLoose) {
          score = sameCategory ? 1 : 0.5;
        }
        if (score > bestScore) {
          best = task;
          bestScore = score;
          tied = false;
        } else if (score > 0 && score === bestScore) {
          tied = true;
        }
      }
      return tied ? undefined : best;
    },
    [taskBoard]
  );

  const taskStateKey = React.useCallback(
    (task: ProjectTaskItem): string => task.source_recommendation_key ?? `task-${task.id}`,
    []
  );

  const isDoneFor = React.useCallback(
    (rec: ConsolidatedFix): boolean => {
      const task = taskForRecommendation(rec);
      if (!task) {
        return false;
      }
      return (optimisticStatus[taskStateKey(task)] ?? task.status) === "done";
    },
    [optimisticStatus, taskForRecommendation, taskStateKey]
  );

  const isPendingFor = React.useCallback(
    (rec: ConsolidatedFix): boolean => {
      const task = taskForRecommendation(rec);
      return task ? pendingKeys.has(taskStateKey(task)) : false;
    },
    [pendingKeys, taskForRecommendation, taskStateKey]
  );

  const hasCardErrorFor = React.useCallback(
    (rec: ConsolidatedFix): boolean => {
      const task = taskForRecommendation(rec);
      return task ? cardErrors.has(taskStateKey(task)) : false;
    },
    [cardErrors, taskForRecommendation, taskStateKey]
  );

  const setPendingKey = (key: string, on: boolean) => {
    setPendingKeys((prev) => {
      const next = new Set(prev);
      if (on) {
        next.add(key);
      } else {
        next.delete(key);
      }
      return next;
    });
  };

  const setCardErrorKey = (key: string, on: boolean) => {
    setCardErrors((prev) => {
      const next = new Set(prev);
      if (on) {
        next.add(key);
      } else {
        next.delete(key);
      }
      return next;
    });
  };

  const applyStatusUpdate = React.useCallback(
    async (
      key: string,
      nextStatus: "done" | "todo",
      mutation: () => Promise<ProjectTaskItem | null>
    ) => {
      setCardErrorKey(key, false);
      setOptimisticStatus((prev) => ({ ...prev, [key]: nextStatus }));
      setPendingKey(key, true);
      try {
        await mutation();
        void loadTaskBoard().catch(() => setBoardFailed(true));
      } catch {
        setOptimisticStatus((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
        setCardErrorKey(key, true);
      } finally {
        setPendingKey(key, false);
      }
    },
    [loadTaskBoard]
  );

  const handleMarkDone = React.useCallback(
    async (rec: ConsolidatedFix) => {
      const task = taskForRecommendation(rec);
      if (!task || task.status === "done" || isPendingFor(rec)) {
        return;
      }
      const stateKey = taskStateKey(task);
      void applyStatusUpdate(stateKey, "done", async () => {
        const token = await getToken();
        if (!token) {
          throw new Error("not signed in");
        }
        return await updateProjectTask(
          projectId!,
          task.id,
          { status: "done" },
          { Authorization: `Bearer ${token}` }
        );
      });
    },
    [applyStatusUpdate, getToken, isPendingFor, projectId, taskForRecommendation, taskStateKey]
  );

  const handleUntick = React.useCallback(
    async (task: ProjectTaskItem) => {
      const stateKey = taskStateKey(task);
      if (pendingKeys.has(stateKey)) {
        return;
      }
      void applyStatusUpdate(stateKey, "todo", async () => {
        const token = await getToken();
        if (!token) {
          throw new Error("not signed in");
        }
        return await updateProjectTask(
          projectId!,
          task.id,
          { status: "todo" },
          { Authorization: `Bearer ${token}` }
        );
      });
    },
    [applyStatusUpdate, getToken, pendingKeys, projectId, taskStateKey]
  );

  const activeRecommendations = useMemo(
    () => allFilteredRecommendations.filter((rec) => !isDoneFor(rec)),
    [allFilteredRecommendations, isDoneFor]
  );

  const doneEntries = useMemo(() => {
    const seen = new Set<string>();
    const entries: Array<{
      key: string;
      task: ProjectTaskItem;
      rec: ConsolidatedFix | null;
    }> = [];
    for (const rec of allFilteredRecommendations) {
      const task = taskForRecommendation(rec);
      if (!task || !isDoneFor(rec)) {
        continue;
      }
      const stateKey = taskStateKey(task);
      if (!seen.has(stateKey)) {
        seen.add(stateKey);
        entries.push({ key: stateKey, task, rec });
      }
    }
    for (const task of taskBoard?.tasks ?? []) {
      const stateKey = taskStateKey(task);
      const status = optimisticStatus[stateKey] ?? task.status;
      if (status !== "done" || seen.has(stateKey)) {
        continue;
      }
      seen.add(stateKey);
      const rec = allFilteredRecommendations.find((r) => taskForRecommendation(r) === task) ?? null;
      entries.push({ key: stateKey, task, rec });
    }
    entries.sort((a, b) => (b.task.resolved_at ?? "").localeCompare(a.task.resolved_at ?? ""));
    return entries;
  }, [
    allFilteredRecommendations,
    isDoneFor,
    optimisticStatus,
    taskBoard,
    taskForRecommendation,
    taskStateKey,
  ]);

  const resolutionTextFor = React.useCallback(
    (task: ProjectTaskItem, rec: ConsolidatedFix | null): string => {
      if (task.verified_at) {
        return t("signalFixes.done.verified");
      }
      const latestCheckAt = taskBoard?.latest_audit_at ?? null;
      const stillPresent =
        task.resolution_source === "manual" &&
        rec !== null &&
        latestCheckAt !== null &&
        task.resolved_at !== null &&
        latestCheckAt > task.resolved_at;
      if (stillPresent) {
        return t("signalFixes.done.stillPresent");
      }
      return t("signalFixes.done.pending");
    },
    [t, taskBoard]
  );

  const formatDoneDate = React.useCallback((iso: string | null): string => {
    if (!iso) {
      return "";
    }
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
  }, []);

  const canEditTasks = taskBoard?.can_edit !== false;

  const pageCount = Math.max(1, Math.ceil(activeRecommendations.length / RECOMMENDATIONS_PER_PAGE));
  const displayPage = Math.min(currentPage, pageCount - 1);
  const pageRecommendations = activeRecommendations.slice(
    displayPage * RECOMMENDATIONS_PER_PAGE,
    displayPage * RECOMMENDATIONS_PER_PAGE + RECOMMENDATIONS_PER_PAGE
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="flex items-center gap-3 text-sm font-medium text-(--t-2) animate-pulse">
          <Activity className="h-4 w-4" /> {t("signalFixes.loading")}
        </div>
      </div>
    );
  }

  if (!latestAudit) {
    return (
      <GlassCard className="flex flex-col items-center justify-center border-(--line) bg-(--panel) p-6 text-center sm:p-12">
        <Lightbulb className="h-12 w-12 text-(--t-3) mb-4" />
        <h2 className="mb-2 text-lg font-semibold tracking-tight text-(--t-1)">
          {t("signalFixes.firstCheck.title")}
        </h2>
        <p className="mb-6 max-w-sm text-sm font-medium text-(--t-2)">
          {t("signalFixes.firstCheck.body")}
        </p>
        <Button
          variant="primary"
          onClick={() => router.push(`/dashboard/audit?projectId=${projectId}`)}
        >
          {t("signalFixes.firstCheck.cta")} <ArrowRight className="h-4 w-4 ml-2" />
        </Button>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-8">
      {/* Filtering Header */}
      {!lockFilter && (
        <GlassCard className="border-(--line) bg-(--panel) p-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
            <div className="flex items-center gap-3 text-xs font-medium text-(--t-3)">
              <Filter className="h-4 w-4 text-(--primary-hover)" /> {t("signalFixes.filters.show")}
            </div>

            <div
              className="flex flex-wrap gap-2.5"
              role="group"
              aria-label={t("signalFixes.filters.aria")}
            >
              {[
                {
                  id: "all",
                  label: t("signalFixes.filters.all"),
                  icon: <TrendingUp className="h-3.5 w-3.5" />,
                },
                {
                  id: "seo",
                  label: t("signalFixes.engines.seo"),
                  icon: <Search className="h-3.5 w-3.5" />,
                },
                {
                  id: "aeo",
                  label: t("signalFixes.engines.aeo"),
                  icon: <Sparkles className="h-3.5 w-3.5" />,
                },
                {
                  id: "geo",
                  label: t("signalFixes.engines.geo"),
                  icon: <GeoIcon className="h-3.5 w-3.5" />,
                },
              ].map((f) => (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={filter === f.id}
                  onClick={() => {
                    setFilter(f.id as RecommendationFilter);
                    setCurrentPage(0);
                  }}
                  className={cx(
                    "flex min-h-11 items-center gap-2.5 rounded border px-4 py-2.5 text-sm font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)",
                    filter === f.id
                      ? "border-[color-mix(in_srgb,var(--purple)_40%,transparent)] bg-(--purple-s) text-(--t-1)"
                      : "border-(--line) bg-(--paper) text-(--t-3) hover:border-(--t-3) hover:text-(--t-2)"
                  )}
                >
                  {f.icon}
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </GlassCard>
      )}

      {/* Integrity Review Banner, surfaces claim review status with link to review queue */}
      {integritySnapshot && integritySnapshot.reviewClaimCount > 0 && latestAudit && (
        <div
          className={cx(
            "rounded border p-4 md:px-6 md:py-5",
            integritySnapshot.flagged
              ? "border-[color-mix(in_srgb,var(--warn)_30%,transparent)] bg-[color-mix(in_srgb,var(--warn)_8%,var(--panel))]"
              : "border-[color-mix(in_srgb,var(--good)_30%,transparent)] bg-[color-mix(in_srgb,var(--good)_8%,var(--panel))]"
          )}
        >
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-4">
              <div
                className={cx(
                  "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border shadow-inner",
                  integritySnapshot.flagged
                    ? "border-[color-mix(in_srgb,var(--warn)_30%,transparent)] bg-[color-mix(in_srgb,var(--warn)_10%,var(--panel))]"
                    : "border-[color-mix(in_srgb,var(--good)_30%,transparent)] bg-[color-mix(in_srgb,var(--good)_10%,var(--panel))]"
                )}
              >
                <AlertTriangle
                  className={cx(
                    "h-5 w-5",
                    integritySnapshot.flagged ? "text-(--warn)" : "text-(--good)"
                  )}
                />
              </div>
              <div className="min-w-0 wrap-break-word">
                <p
                  className={cx(
                    "text-sm font-bold",
                    integritySnapshot.flagged ? "text-(--warn)" : "text-(--good)"
                  )}
                >
                  {t("signalFixes.integrity.needReview", {
                    count: integritySnapshot.reviewClaimCount,
                  })}
                </p>
                <p className="text-xs font-medium text-(--t-2)">
                  {integritySnapshot.flaggedClaims > 0 &&
                    t("signalFixes.integrity.flagged", {
                      count: integritySnapshot.flaggedClaims,
                    })}
                  {integritySnapshot.flaggedClaims > 0 &&
                    integritySnapshot.omittedClaims > 0 &&
                    " · "}
                  {integritySnapshot.omittedClaims > 0 &&
                    t("signalFixes.integrity.omitted", {
                      count: integritySnapshot.omittedClaims,
                    })}
                  {(integritySnapshot.flaggedClaims > 0 || integritySnapshot.omittedClaims > 0) &&
                    " · "}
                  {t("signalFixes.integrity.total", { count: integritySnapshot.totalClaims })}
                  {integritySnapshot.groundingProfileLabel &&
                    ` · ${integritySnapshot.groundingProfileLabel}`}
                </p>
              </div>
            </div>
            <Link
              href={`/dashboard/audit/${latestAudit.id}?tab=review_queue`}
              className={cx(
                "inline-flex min-h-11 items-center gap-2.5 rounded border px-5 py-2.5 text-xs font-bold transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)",
                integritySnapshot.flagged
                  ? "border-[color-mix(in_srgb,var(--warn)_40%,transparent)] bg-(--panel) text-(--warn) hover:bg-[color-mix(in_srgb,var(--warn)_12%,var(--panel))]"
                  : "border-[color-mix(in_srgb,var(--good)_40%,transparent)] bg-(--panel) text-(--good) hover:bg-[color-mix(in_srgb,var(--good)_12%,var(--panel))]"
              )}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              {t("signalFixes.integrity.open")}
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      )}

      {/* Results Grid */}
      {normalizedAudit?.diagnostics.degraded ? (
        <div className="rounded border border-[color-mix(in_srgb,var(--warn)_30%,transparent)] bg-[color-mix(in_srgb,var(--warn)_8%,var(--panel))] p-4 text-sm text-(--t-1)">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-(--warn)" />
            <div className="min-w-0 flex-1 space-y-1 wrap-break-word">
              <p className="font-medium">{normalizedAudit.diagnostics.summary}</p>
              {normalizedAudit.diagnostics.issues.length > 1 ? (
                <button
                  type="button"
                  aria-expanded={diagnosticsExpanded}
                  onClick={() => setDiagnosticsExpanded((prev) => !prev)}
                  className="inline-flex min-h-11 items-center gap-1.5 text-xs font-medium text-(--warn) hover:text-(--t-1) transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)"
                >
                  {diagnosticsExpanded
                    ? t("signalFixes.diagnostics.hide")
                    : t("signalFixes.diagnostics.show")}{" "}
                  {t("signalFixes.diagnostics.details", {
                    count: normalizedAudit.diagnostics.issues.length,
                  })}
                  <ChevronDown
                    className={cx(
                      "h-3.5 w-3.5 transition-transform duration-200",
                      diagnosticsExpanded && "rotate-180"
                    )}
                  />
                </button>
              ) : null}
              {diagnosticsExpanded && normalizedAudit.diagnostics.issues.length > 1 ? (
                <ul className="mt-3 space-y-2 border-t border-[color-mix(in_srgb,var(--warn)_25%,transparent)] pt-3 text-xs text-(--t-2)">
                  {normalizedAudit.diagnostics.issues.map((issue) => (
                    <li key={issue} className="leading-relaxed">
                      &bull; {issue}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {activeRecommendations.length === 0 ? (
        <div className="rounded border border-dashed border-(--line) bg-(--panel) p-8 text-center">
          <p className="text-sm font-medium text-(--t-3)">
            {allFilteredRecommendations.length === 0
              ? t("signalFixes.noMatches")
              : t("signalFixes.done.allDone")}
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AnimatePresence mode="popLayout">
              {pageRecommendations.map((rec, idx) => {
                const globalIndex = displayPage * RECOMMENDATIONS_PER_PAGE + idx;
                const recTask = taskForRecommendation(rec);
                const trackingKey = `hub:${rec.title}`;
                const trackedExport = getTrackedExport(trackingKey);
                const annotationTarget =
                  annotationTargetsByTitle.get(rec.title.toLowerCase()) ?? null;
                const annotationKey =
                  annotationTarget?.sectionPath || annotationTarget?.sourceRecommendationKey || "";
                const annotationCount = annotationTarget ? annotationCounts[annotationKey] || 0 : 0;
                const isAnnotationExpanded =
                  annotationTarget?.sectionPath === expandedAnnotationPath;
                const isTechnical = rec.category.toLowerCase().includes("technical");
                const isSEO =
                  (rec.engines.includes("SEO") || rec.category.toLowerCase().includes("seo")) &&
                  !isTechnical;
                const isAEO =
                  rec.engines.includes("AEO") ||
                  rec.category.toLowerCase().includes("aeo") ||
                  rec.category.toLowerCase().includes("answer");
                const isGEO =
                  rec.engines.includes("GEO") ||
                  rec.category.toLowerCase().includes("geo") ||
                  rec.category.toLowerCase().includes("citation");

                const pillars = PILLAR_ORDER.filter((e) => rec.engines.includes(e));
                const visiblePillars =
                  filter === "all" ? pillars : pillars.filter((e) => e.toLowerCase() !== filter);
                const pillarNames = visiblePillars.map((e) =>
                  t(`signalFixes.engines.${e.toLowerCase()}`)
                );
                const pillarList =
                  pillarNames.length > 1
                    ? `${pillarNames.slice(0, -1).join(t("signalFixes.listSeparator"))} ${t("signalFixes.and")} ${pillarNames[pillarNames.length - 1]}`
                    : pillarNames[0];
                const marker =
                  pillars.length > 1 && visiblePillars.length > 0
                    ? t(filter === "all" ? "signalFixes.helps" : "signalFixes.alsoHelps", {
                        list: pillarList,
                      })
                    : null;

                const CategoryIcon = isTechnical
                  ? Search
                  : isSEO
                    ? Search
                    : isAEO
                      ? Sparkles
                      : isGEO
                        ? GeoIcon
                        : Lightbulb;
                const categoryColor = isTechnical
                  ? "text-(--t-1) bg-(--blue-s) border-[color-mix(in_srgb,var(--blue)_30%,transparent)]"
                  : isSEO
                    ? "text-(--t-1) bg-(--blue-s) border-[color-mix(in_srgb,var(--blue)_30%,transparent)]"
                    : isAEO
                      ? "text-(--primary-hover) bg-(--purple-s) border-[color-mix(in_srgb,var(--purple)_30%,transparent)]"
                      : isGEO
                        ? "text-(--good) bg-[color-mix(in_srgb,var(--good)_8%,var(--panel))] border-[color-mix(in_srgb,var(--good)_30%,transparent)]"
                        : "text-(--primary-hover) bg-(--purple-s) border-[color-mix(in_srgb,var(--purple)_30%,transparent)]";

                const priorityColor =
                  rec.impact === "Critical"
                    ? "text-(--bad) bg-[color-mix(in_srgb,var(--bad)_8%,var(--panel))] border-[color-mix(in_srgb,var(--bad)_30%,transparent)]"
                    : rec.impact === "Strategic"
                      ? "text-(--warn) bg-[color-mix(in_srgb,var(--warn)_8%,var(--panel))] border-[color-mix(in_srgb,var(--warn)_30%,transparent)]"
                      : "text-(--t-2) bg-(--paper) border-(--line)";

                return (
                  <motion.div
                    key={`${rec.title}-${globalIndex}`}
                    className="min-w-0"
                    layout
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.3, delay: idx * 0.05 }}
                  >
                    <GlassCard className="group relative flex h-full min-w-0 flex-col gap-6 overflow-hidden rounded border-(--line) bg-(--panel) p-5 transition-colors hover:border-(--t-3) md:p-6">
                      <div className="flex flex-wrap justify-between items-start gap-3 relative z-10">
                        <div
                          className={cx(
                            "flex max-w-full items-center gap-2 rounded border px-3 py-1.5 text-xs font-medium wrap-break-word",
                            categoryColor
                          )}
                        >
                          <CategoryIcon className="h-4 w-4 shrink-0" />
                          {rec.category.toLowerCase() === "seo" ||
                          rec.category.toLowerCase() === "aeo" ||
                          rec.category.toLowerCase() === "geo"
                            ? t(`signalFixes.engines.${rec.category.toLowerCase()}`)
                            : rec.category.toLowerCase().includes("technical")
                              ? t("signalFixes.category.technical")
                              : t("signalFixes.category.general")}
                        </div>
                        <div
                          className={cx(
                            "flex items-center gap-2 rounded border px-3 py-1.5 text-xs font-medium",
                            priorityColor
                          )}
                        >
                          {rec.impact === "Critical" ? (
                            <AlertCircle className="w-3.5 h-3.5" />
                          ) : rec.impact === "Strategic" ? (
                            <TrendingUp className="w-3.5 h-3.5" />
                          ) : (
                            <ShieldCheck className="w-3.5 h-3.5" />
                          )}
                          {rec.impact === "Critical"
                            ? t("signalFixes.impact.critical")
                            : rec.impact === "Strategic"
                              ? t("signalFixes.impact.strategic")
                              : rec.impact === "Optimization"
                                ? t("signalFixes.impact.optimization")
                                : t("signalFixes.impact.other")}
                        </div>
                        {/* SIGV2-1193: which channel raised this row. The
                            Improve list and the action plan are one list now,
                            so provenance moves onto the row. */}
                        {fixSourceLabelKeys(rec.sources).map((key) => (
                          <div
                            key={key}
                            className="flex items-center gap-2 rounded border-0 bg-[#EEF1F6] px-3 py-1.5 text-xs font-medium text-(--t-3)"
                          >
                            {t(key)}
                          </div>
                        ))}
                        {(rec.confidence === "high" ||
                          rec.confidence === "medium" ||
                          rec.confidence === "low") && (
                          <div
                            className={cx(
                              "flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs font-medium",
                              rec.confidence === "high"
                                ? "text-(--good) bg-[color-mix(in_srgb,var(--good)_8%,var(--panel))] border-[color-mix(in_srgb,var(--good)_30%,transparent)]"
                                : rec.confidence === "medium"
                                  ? "text-(--warn) bg-[color-mix(in_srgb,var(--warn)_8%,var(--panel))] border-[color-mix(in_srgb,var(--warn)_30%,transparent)]"
                                  : "text-(--bad) bg-[color-mix(in_srgb,var(--bad)_8%,var(--panel))] border-[color-mix(in_srgb,var(--bad)_30%,transparent)]"
                            )}
                          >
                            {rec.confidence === "high" ? (
                              <CheckCircle2 className="w-3.5 h-3.5" />
                            ) : rec.confidence === "medium" ? (
                              <HelpCircle className="w-3.5 h-3.5" />
                            ) : (
                              <AlertTriangle className="w-3.5 h-3.5" />
                            )}
                            {t(`signalFixes.confidence.${rec.confidence}`)}
                          </div>
                        )}
                      </div>

                      <div className="min-w-0 space-y-4 relative z-10">
                        <h2
                          title={rec.title}
                          className="break-normal text-xl font-semibold text-(--t-1) leading-tight tracking-tight"
                        >
                          {rec.title}
                        </h2>
                        {rec.description && (
                          <p className="break-normal border-l-2 border-(--line) pl-4 text-sm font-medium leading-relaxed text-(--t-2) group-hover:border-[color-mix(in_srgb,var(--purple)_40%,transparent)]">
                            {rec.description}
                          </p>
                        )}
                        {marker && <p className="text-xs font-medium text-(--t-3)">{marker}</p>}

                        {/* Enriched context row for penalty-sourced items */}
                        {(rec.section || rec.page || rec.impactValue !== undefined) && (
                          <div className="flex flex-wrap items-center gap-2.5 pt-1">
                            {rec.section && (
                              <span className="inline-flex max-w-full items-center gap-1.5 wrap-break-word rounded border-0 bg-[#EEF1F6] px-2.5 py-1 text-xs font-mono text-(--t-2)">
                                {rec.section}
                              </span>
                            )}
                            {rec.page && (
                              <span
                                className="inline-flex max-w-full items-center gap-1.5 break-all rounded border-0 bg-[#EEF1F6] px-2.5 py-1 text-xs font-mono text-(--t-3)"
                                title={rec.page}
                              >
                                {(() => {
                                  try {
                                    return new URL(rec.page).hostname;
                                  } catch {
                                    return rec.page;
                                  }
                                })()}
                              </span>
                            )}
                            {typeof rec.impactValue === "number" && (
                              <span
                                className={cx(
                                  "inline-flex items-center rounded border px-2.5 py-1 text-xs font-bold",
                                  rec.impactValue < 0
                                    ? "text-(--bad) border-[color-mix(in_srgb,var(--bad)_30%,transparent)] bg-[color-mix(in_srgb,var(--bad)_6%,var(--panel))]"
                                    : "text-(--good) border-[color-mix(in_srgb,var(--good)_30%,transparent)] bg-[color-mix(in_srgb,var(--good)_6%,var(--panel))]"
                                )}
                              >
                                {rec.impactValue > 0 ? "+" : ""}
                                {t("signalFixes.points", { value: rec.impactValue })}
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      <div className="relative z-10 mt-auto border-t border-(--line) pt-5">
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
                          <div className="flex shrink-0 items-center gap-3">
                            <div className="flex h-6 w-6 items-center justify-center rounded border-0 bg-[#EEF1F6] text-xs font-medium text-(--t-3)">
                              {globalIndex + 1}
                            </div>
                            <span className="whitespace-nowrap font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                              {t("signalFixes.rank")}
                            </span>
                          </div>
                          <div className="ml-auto flex flex-wrap items-center justify-end gap-3">
                            {canEditTasks ? (
                              recTask ? (
                                <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded border-0 bg-[#EEF1F6] px-3 py-1.5 text-xs font-medium text-(--t-2) transition hover:border-(--t-3) hover:text-(--t-1) focus-within:outline-hidden focus-within:ring-2 focus-within:ring-(--blue)">
                                  <input
                                    type="checkbox"
                                    className="h-4 w-4 accent-(--blue)"
                                    checked={isDoneFor(rec)}
                                    disabled={isPendingFor(rec)}
                                    onChange={() => void handleMarkDone(rec)}
                                    aria-label={t("signalFixes.done.markLabel", {
                                      title: rec.title,
                                    })}
                                  />
                                  {isPendingFor(rec)
                                    ? t("signalFixes.done.saving")
                                    : t("signalFixes.done.mark")}
                                </label>
                              ) : (
                                <span className="inline-flex min-h-11 items-center gap-2 rounded border border-dashed border-(--line) bg-(--paper) px-3 py-1.5 text-xs font-medium text-(--t-3)">
                                  <input
                                    type="checkbox"
                                    className="h-4 w-4"
                                    disabled
                                    aria-label={t("signalFixes.done.markLabel", {
                                      title: rec.title,
                                    })}
                                  />
                                  {t("signalFixes.done.unavailable")}
                                </span>
                              )
                            ) : null}
                            {annotationTarget ? (
                              <button
                                type="button"
                                aria-expanded={isAnnotationExpanded}
                                onClick={() =>
                                  setExpandedAnnotationPath((current) =>
                                    current === annotationTarget.sectionPath
                                      ? null
                                      : annotationTarget.sectionPath
                                  )
                                }
                                className="inline-flex min-h-11 items-center gap-2 rounded border-0 bg-[#EEF1F6] px-3 py-1.5 text-xs font-medium text-(--t-2) transition hover:border-[color-mix(in_srgb,var(--purple)_40%,transparent)] hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)"
                              >
                                <MessageSquareMore className="h-3.5 w-3.5" />
                                {annotationCount > 0
                                  ? t("signalFixes.comments", { count: annotationCount })
                                  : t("signalFixes.discuss")}
                              </button>
                            ) : null}
                            {trackedExport ? (
                              <>
                                <span className="rounded border border-[color-mix(in_srgb,var(--good)_30%,transparent)] bg-[color-mix(in_srgb,var(--good)_8%,var(--panel))] px-3 py-1.5 text-xs font-medium text-(--good)">
                                  {t("signalFixes.jira.sent")}
                                </span>
                                <a
                                  href={trackedExport.issueUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="flex min-h-11 items-center gap-2 rounded border border-[color-mix(in_srgb,var(--good)_30%,transparent)] bg-[color-mix(in_srgb,var(--good)_8%,var(--panel))] px-3 py-1.5 text-xs font-medium text-(--good) transition-colors hover:bg-[color-mix(in_srgb,var(--good)_14%,var(--panel))] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)"
                                >
                                  {t("signalFixes.jira.ticket", {
                                    key: trackedExport.issueKey,
                                  })}
                                  <ArrowRight className="h-3 w-3" />
                                </a>
                              </>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => router.push(`/dashboard/audit/${latestAudit.id}`)}
                              className="group/btn flex min-h-11 items-center gap-2.5 text-xs font-medium text-(--t-2) transition-colors hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)"
                            >
                              {t("signalFixes.openReport")}{" "}
                              <ArrowRight className="h-4 w-4 transition-transform group-hover/btn:translate-x-1.5" />
                            </button>
                          </div>
                        </div>

                        {hasCardErrorFor(rec) ? (
                          <p role="alert" className="mt-4 text-xs font-medium text-(--bad)">
                            {t("signalFixes.done.error")}
                          </p>
                        ) : null}

                        {annotationTarget && isAnnotationExpanded && latestAudit ? (
                          <div className="mt-6 border-t border-(--line) pt-6">
                            <AuditAnnotationThread
                              auditId={latestAudit.id}
                              sectionPath={annotationTarget.sectionPath}
                              sourceRecommendationKey={annotationTarget.sourceRecommendationKey}
                              title={annotationTarget.title}
                              description={annotationTarget.description}
                              onCountChange={(count) => {
                                setAnnotationCounts((current) => ({
                                  ...current,
                                  [annotationKey]: count,
                                }));
                              }}
                            />
                          </div>
                        ) : null}
                      </div>
                    </GlassCard>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>

          <nav
            aria-label={t("signalFixes.pagination.aria")}
            className="flex flex-wrap items-center justify-between gap-3 rounded border-0 bg-white px-4 py-3"
          >
            <p className="text-xs font-medium text-(--t-2)" aria-live="polite">
              {t("signalFixes.pagination.status", {
                page: displayPage + 1,
                pages: pageCount,
                shown: pageRecommendations.length,
                total: activeRecommendations.length,
              })}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setCurrentPage(Math.max(0, displayPage - 1))}
                disabled={displayPage === 0}
                className="inline-flex min-h-11 items-center rounded border-0 bg-white px-4 text-xs font-semibold text-(--t-1) transition-colors hover:border-(--t-3) disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)"
              >
                {t("signalFixes.pagination.prev")}
              </button>
              <button
                type="button"
                onClick={() => setCurrentPage(Math.min(pageCount - 1, displayPage + 1))}
                disabled={displayPage >= pageCount - 1}
                className="inline-flex min-h-11 items-center rounded border-0 bg-white px-4 text-xs font-semibold text-(--t-1) transition-colors hover:border-(--t-3) disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)"
              >
                {t("signalFixes.pagination.next")}
              </button>
            </div>
          </nav>
        </>
      )}

      {boardFailed ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded border border-[color-mix(in_srgb,var(--bad)_30%,transparent)] bg-[color-mix(in_srgb,var(--bad)_8%,var(--panel))] px-4 py-3 text-sm font-medium text-(--bad)"
        >
          {t("signalFixes.done.boardError")}
          <button
            type="button"
            onClick={() => void loadTaskBoard().catch(() => setBoardFailed(true))}
            className="inline-flex min-h-11 items-center rounded border border-[color-mix(in_srgb,var(--bad)_40%,transparent)] bg-(--panel) px-4 text-xs font-semibold text-(--bad) transition-colors hover:bg-[color-mix(in_srgb,var(--bad)_12%,var(--panel))] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue)"
          >
            {t("common.tryAgain")}
          </button>
        </div>
      ) : null}

      {doneEntries.length > 0 ? (
        <section aria-labelledby="fixes-done-heading">
          <h3
            id="fixes-done-heading"
            className="text-xs font-semibold uppercase tracking-[0.08em] text-(--t-3)"
          >
            {t("signalFixes.done.sectionTitle")}
          </h3>
          <ul className="mt-3 space-y-2">
            {doneEntries.map((entry) => {
              const title = entry.task.title || entry.rec?.title || "";
              const doneDate = formatDoneDate(entry.task.resolved_at);
              return (
                <li
                  key={entry.key}
                  className="rounded border-0 bg-white px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-(--good)" aria-hidden="true" />
                    <span className="min-w-0 flex-1 wrap-break-word text-sm font-medium text-(--t-2)">
                      {title}
                    </span>
                    {canEditTasks ? (
                      <button
                        type="button"
                        disabled={pendingKeys.has(entry.key)}
                        onClick={() => void handleUntick(entry.task)}
                        className="inline-flex min-h-11 items-center rounded border-0 bg-[#EEF1F6] px-4 text-xs font-medium text-(--t-2) transition-colors hover:border-(--t-3) hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--blue) disabled:opacity-50"
                      >
                        {t("signalFixes.done.undo")}
                      </button>
                    ) : null}
                  </div>
                  <p className="mt-1.5 wrap-break-word text-xs font-medium text-(--t-3)">
                    {doneDate ? (
                      <span>
                        {t("signalFixes.done.doneAt", { date: doneDate })}
                        {" · "}
                      </span>
                    ) : null}
                    <span>{resolutionTextFor(entry.task, entry.rec)}</span>
                  </p>
                  {cardErrors.has(entry.key) ? (
                    <p role="alert" className="mt-2 text-xs font-medium text-(--bad)">
                      {t("signalFixes.done.error")}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
