"use client";

// Rebuilt 1:1 with signal-MVP Signal Competitors.html, bound to REAL data end to end:
// per-competitor question wins from the audit report, add/remove competitor, numeric
// scores and head-to-head gaps all come from the real competitor benchmark CRUD
// (`project_competitors` table), the competitive-analysis endpoints and the latest
// audit's aeo_site_stats.competitor_snippet_comparisons. Competitive intelligence is a
// Pro feature; on plans without it we show the MVP Pro gate over an honest empty
// backdrop, no fabricated competitors, scores, wins or gaps.
// Pure .sg markup + `.sg .competitors` overrides.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/custom-auth";
import SignalAddCompetitorModal from "@/components/signal/SignalAddCompetitorModal";
import SignalUpgradeGate from "@/components/signal/SignalUpgradeGate";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { getPlanLockContent } from "@/lib/planLocks";
import { resolvePlanType } from "@/lib/planCapabilities";
import { useSignalEntrance } from "@/hooks/useSignalChartMotion";
import { deriveCompetitorQuestionWins } from "@/lib/competitorQuestionWins";
import SignalCrumb from "@/components/signal/SignalCrumb";
import { SkelCard } from "@/components/signal/SignalSkeleton";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalExportMenu from "@/components/signal/SignalExportMenu";
import { cx } from "@/components/ui/utils";
import { isAuditResult } from "@/types/auditResult";
import {
  deleteProjectCompetitor,
  fetchProjectCompetitiveAnalysis,
  fetchProjectCompetitiveGaps,
  fetchProjectCompetitiveTrends,
  fetchProjectCompetitors,
  refreshProjectCompetitiveAnalysis,
  type CompetitiveMetric,
  type ProjectCompetitiveAnalysisResponse,
  type ProjectCompetitiveGapItem,
  type ProjectCompetitiveTrendLine,
  type ProjectCompetitiveTrendResponse,
  type ProjectCompetitorListItem,
} from "@/services/workspaceService";

const MAX_COMPETITORS = 5;

const roundOrNull = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null;

const GAP_METRIC_LABEL_KEY: Record<string, string> = {
  seo: "signalCompetitors.metric.search",
  aeo: "signalCompetitors.metric.answers",
  geo: "signalCompetitors.metric.recommendations",
};

// Competitor series colours after the project line (always --purple).
const LINE_COLORS = ["var(--bad)", "var(--t-3)", "var(--blue)", "var(--warn)", "var(--good)"];

type ScoresLike = { aeo: number | null; geo: number | null } | null | undefined;

// AIO is the product's AEO+GEO roll-up: mean of the present scores, the same
// definition getAioView uses. Never raw `aeo` alone.
const aioScore = (scores: ScoresLike): number | null => {
  if (!scores) return null;
  const present = [scores.aeo, scores.geo].filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v)
  );
  return present.length
    ? Math.round(present.reduce((sum, v) => sum + v, 0) / present.length)
    : null;
};

// First-minus-last non-null point of a trend line; null when history is
// too thin to state a change.
const lineChange = (line: ProjectCompetitiveTrendLine | undefined): number | null => {
  const values = (line?.points ?? [])
    .map((p) => p.value)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  return values.length >= 2 ? values[values.length - 1] - values[0] : null;
};

const lineForCompetitor = (
  lines: ProjectCompetitiveTrendLine[] | undefined,
  competitor: ProjectCompetitorListItem
): ProjectCompetitiveTrendLine | undefined =>
  lines?.find(
    (line) =>
      !line.is_project &&
      (line.key === String(competitor.id) ||
        line.label === competitor.display_name ||
        line.label === competitor.normalized_domain)
  );

type ChartMetric = "overall" | "aio" | "seo";
const CHART_METRICS: ChartMetric[] = ["overall", "aio", "seo"];

const formatEvidenceDate = (timestamp: string | null): string | null => {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
};

export default function ProjectCompetitorsPage() {
  const { t, i18n } = useTranslation();
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const base = `/dashboard/projects/${projectId}`;
  const { getToken } = useAuth();

  const {
    project,
    latestAudit,
    loading: accessLoading,
  } = useProjectLatestAudit(projectId, {
    includeFullReport: true,
  });

  const [competitors, setCompetitors] = useState<ProjectCompetitorListItem[]>([]);
  const [analysis, setAnalysis] = useState<ProjectCompetitiveAnalysisResponse | null>(null);
  const [gaps, setGaps] = useState<ProjectCompetitiveGapItem[]>([]);
  const entranceRef = useSignalEntrance(
    `comp:${analysis ? "1" : "0"}:${competitors.length}:${gaps.length}`
  );
  const [loadingCompetitive, setLoadingCompetitive] = useState(true);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [upgradeGateOpen, setUpgradeGateOpen] = useState(true);
  const [expandedCompetitorId, setExpandedCompetitorId] = useState<number | null>(null);
  const [chartMetric, setChartMetric] = useState<ChartMetric>("overall");
  const [chartTrend, setChartTrend] = useState<ProjectCompetitiveTrendResponse | null>(null);
  const [trend30, setTrend30] = useState<ProjectCompetitiveTrendResponse | null>(null);
  const [benchmarkBusy, setBenchmarkBusy] = useState(false);

  // Feature access: competitive intelligence is Pro-gated. Treat as locked unless
  // the backend explicitly grants it.
  const benchmarkAccess = (
    project as {
      feature_access?: {
        benchmark_intelligence?: { allowed?: boolean; required_plan?: string | null };
      };
    } | null
  )?.feature_access?.benchmark_intelligence;
  const allowed = Boolean(benchmarkAccess?.allowed);
  const rawRequiredPlan =
    typeof benchmarkAccess?.required_plan === "string" ? benchmarkAccess.required_plan.trim() : "";
  const competitorBase = getPlanLockContent("competitiveIntelligence");
  const requiredPlanLabel = rawRequiredPlan || competitorBase.requiredPlanLabel;
  const canonicalPlan = resolvePlanType(`plan_${requiredPlanLabel.toLowerCase()}`);
  const competitorLock = getPlanLockContent("competitiveIntelligence", {
    requiredPlanLabel: rawRequiredPlan || undefined,
    href: canonicalPlan
      ? `/dashboard/billing?section=plans&plan=${canonicalPlan}`
      : competitorBase.href,
  });
  // feature_access arrives asynchronously; deciding while `project` is still null
  // flashes the upgrade gate at users who do have access.
  const locked = !accessLoading && !allowed;

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const loadCompetitive = useCallback(async () => {
    if (!projectId || accessLoading || !allowed) {
      setLoadingCompetitive(false);
      return;
    }
    setLoadingCompetitive(true);
    try {
      const headers = await getAuthHeaders();
      const [competitorsResult, analysisResult, gapsResult, trend30Result] =
        await Promise.allSettled([
          fetchProjectCompetitors(projectId, headers),
          fetchProjectCompetitiveAnalysis(projectId, headers),
          fetchProjectCompetitiveGaps(projectId, headers),
          fetchProjectCompetitiveTrends(projectId, headers, {
            period: "30d",
            metric: "overall",
          }),
        ]);
      setCompetitors(competitorsResult.status === "fulfilled" ? competitorsResult.value : []);
      setAnalysis(analysisResult.status === "fulfilled" ? analysisResult.value : null);
      setGaps(gapsResult.status === "fulfilled" ? gapsResult.value.gaps : []);
      setTrend30(trend30Result.status === "fulfilled" ? trend30Result.value : null);
    } finally {
      setLoadingCompetitive(false);
    }
  }, [accessLoading, allowed, getAuthHeaders, projectId]);

  useEffect(() => {
    void loadCompetitive();
  }, [loadCompetitive]);

  // Chart history. The endpoint honours one metric per call; the AIO toggle
  // needs the AEO+GEO roll-up, so it fetches both and merges per line/date.
  useEffect(() => {
    if (!projectId || accessLoading || !allowed) {
      setChartTrend(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const headers = await getAuthHeaders();
        if (chartMetric === "aio") {
          const [aeo, geo] = await Promise.all([
            fetchProjectCompetitiveTrends(projectId, headers, {
              period: "1y",
              metric: "aeo",
            }),
            fetchProjectCompetitiveTrends(projectId, headers, {
              period: "1y",
              metric: "geo",
            }),
          ]);
          if (cancelled) return;
          const merged: ProjectCompetitiveTrendResponse = {
            ...aeo,
            metric: "aeo",
            lines: aeo.lines.map((line, idx) => ({
              ...line,
              points: line.points.map((point, pIdx) => {
                const other = geo.lines[idx]?.points?.[pIdx];
                const values = [point.value, other?.value].filter(
                  (v): v is number => typeof v === "number" && Number.isFinite(v)
                );
                return {
                  date: point.date,
                  value: values.length ? values.reduce((s, v) => s + v, 0) / values.length : null,
                };
              }),
            })),
          };
          setChartTrend(merged);
        } else {
          const trend = await fetchProjectCompetitiveTrends(projectId, headers, {
            period: "1y",
            metric: chartMetric as CompetitiveMetric,
          });
          if (!cancelled) setChartTrend(trend);
        }
      } catch {
        if (!cancelled) setChartTrend(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, accessLoading, allowed, chartMetric, getAuthHeaders]);

  // Export: the `.exp-menu` control (SIGV2-1124). This screen is the one that
  // leads with the Competitors report (SIGV2-1255), first in the list.
  const auditId = typeof latestAudit?.id === "number" ? latestAudit.id : null;

  const handleRemove = useCallback(
    async (competitorId: number) => {
      if (!projectId) return;
      setRemovingId(competitorId);
      try {
        const headers = await getAuthHeaders();
        await deleteProjectCompetitor(projectId, competitorId, headers);
        toast.success(t("signalCompetitors.toast.removed"));
        await loadCompetitive();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("signalCompetitors.toast.removeError"));
      } finally {
        setRemovingId(null);
      }
    },
    [getAuthHeaders, loadCompetitive, projectId, t]
  );

  // SIGV2-1095: competitor benchmarks only enqueue on scheduled audits, so a
  // competitor added before a manual scan stays unmeasured. The refresh
  // endpoint exists; surface it and show each competitor's real status.
  const unmeasured = useMemo(
    () => competitors.filter((c) => c.latest_status !== "succeeded"),
    [competitors]
  );

  const runBenchmark = useCallback(async () => {
    if (!projectId || benchmarkBusy) return;
    setBenchmarkBusy(true);
    try {
      const headers = await getAuthHeaders();
      await refreshProjectCompetitiveAnalysis(projectId, headers);
      toast.success(t("signalCompetitors.benchmark.queued"));
      await loadCompetitive();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("signalCompetitors.benchmark.failedToast")
      );
    } finally {
      setBenchmarkBusy(false);
    }
  }, [benchmarkBusy, getAuthHeaders, loadCompetitive, projectId, t]);

  const report = useMemo(() => {
    const raw = latestAudit?.full_report;
    return isAuditResult(raw) ? raw : null;
  }, [latestAudit?.full_report]);

  const comparisons = useMemo(
    () => report?.aeo_site_stats?.competitor_snippet_comparisons ?? [],
    [report]
  );

  const questionWins = useMemo(
    () =>
      deriveCompetitorQuestionWins(
        comparisons,
        competitors.map((c) => ({
          id: c.id,
          normalized_domain: c.normalized_domain,
          display_name: c.display_name,
        }))
      ),
    [comparisons, competitors]
  );

  const winsByCompetitor = useMemo(
    () => new Map(questionWins.perCompetitor.map((s) => [s.competitorId, s])),
    [questionWins]
  );

  const gapReasonByCompetitor = useMemo(() => {
    const map = new Map<number, ProjectCompetitiveGapItem>();
    for (const gap of gaps) {
      if (!map.has(gap.competitor_id)) map.set(gap.competitor_id, gap);
    }
    return map;
  }, [gaps]);

  const analysisByCompetitor = useMemo(
    () => new Map((analysis?.competitors ?? []).map((entry) => [entry.id, entry])),
    [analysis]
  );

  const atLimit = competitors.length >= MAX_COMPETITORS;
  const hasCompetitors = competitors.length > 0;
  const hasComparisons = comparisons.length > 0;

  // Approved `.top`: crumb + actions live inside the shared SignalTopBar
  // (registered via the page-header context), never a second row under it.
  const { setHeader } = useWorkspacePageHeader();
  const topCrumb = useMemo(
    () => (
      <SignalCrumb
        items={[
          { label: t("signalCompetitors.nav.dashboard"), href: base },
          { label: t("signalCompetitors.nav.competitors") },
        ]}
      />
    ),
    [t, base]
  );
  const topActions = useMemo(
    () => (
      <>
        <SignalExportMenu
          page="competitors"
          reportKind="competitors"
          auditId={locked ? null : auditId}
          projectId={Number(projectId) || null}
          disabledReason={locked ? t("signalCompetitors.export.locked") : undefined}
        />
        <button
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
          disabled={locked || atLimit}
          title={
            atLimit ? t("signalCompetitors.add.limitTitle", { max: MAX_COMPETITORS }) : undefined
          }
          onClick={() => setAddOpen(true)}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M12 5v14M5 12h14" />
          </svg>
          {t("signalCompetitors.add.button")}
        </button>
      </>
    ),
    [locked, atLimit, auditId, projectId, t]
  );
  useEffect(() => {
    setHeader({ crumb: topCrumb, actions: topActions });
    return () => setHeader(null);
  }, [setHeader, topCrumb, topActions]);

  // Hero + leaderboard: rank comes from analysis.rank (server-computed over
  // tracked entities); the leader is the top blended-visibility competitor.
  const rankOverall = analysis?.rank?.overall ?? null;
  const trackedCount = competitors.length + 1;
  const projectOverall = roundOrNull(analysis?.project?.scores?.overall);
  const leader = useMemo(() => {
    let best: ProjectCompetitorListItem | null = null;
    let bestScore = -Infinity;
    for (const competitor of competitors) {
      const score = competitor.latest_scores.overall;
      if (typeof score === "number" && Number.isFinite(score) && score > bestScore) {
        best = competitor;
        bestScore = score;
      }
    }
    return best;
  }, [competitors]);
  const leaderScore = leader ? roundOrNull(leader.latest_scores.overall) : null;

  const ordinalRank = useCallback(
    (n: number): string => {
      const rule = new Intl.PluralRules(i18n.language, { type: "ordinal" }).select(n);
      return t(`signalCompetitors.hero.ordinal.${rule}`, {
        n,
        defaultValue: String(n),
      });
    },
    [i18n.language, t]
  );

  // Leaderboard rows: everyone ranked by blended visibility, descending.
  const leaderboardRows = useMemo(() => {
    type Row = {
      key: string;
      name: string;
      sub: string | null;
      isProject: boolean;
      seo: number | null;
      aio: number | null;
      visibility: number | null;
      delta: number | null;
      competitor: ProjectCompetitorListItem | null;
    };
    const rows: Row[] = [];
    if (analysis?.project?.scores) {
      rows.push({
        key: "you",
        name: project?.name || t("signalCompetitors.scores.you"),
        sub: null,
        isProject: true,
        seo: roundOrNull(analysis.project.scores.seo),
        aio: aioScore(analysis.project.scores),
        visibility: projectOverall,
        delta: null,
        competitor: null,
      });
    }
    for (const competitor of competitors) {
      rows.push({
        key: `c-${competitor.id}`,
        name: competitor.display_name,
        sub: competitor.normalized_domain,
        isProject: false,
        seo: roundOrNull(competitor.latest_scores.seo),
        aio: aioScore(competitor.latest_scores),
        visibility: roundOrNull(competitor.latest_scores.overall),
        delta: analysisByCompetitor.get(competitor.id)?.delta.overall ?? null,
        competitor,
      });
    }
    rows.sort((a, b) => (b.visibility ?? -Infinity) - (a.visibility ?? -Infinity));
    return rows;
  }, [analysis, analysisByCompetitor, competitors, project?.name, projectOverall, t]);

  // 30-day column: real per-entity change when the trends feed has >=2 points;
  // otherwise the column falls back to "Gap vs you" and shows delta plainly.
  const projectChange30 = useMemo(
    () => lineChange(trend30?.lines.find((line) => line.is_project)),
    [trend30]
  );
  const has30dHistory =
    projectChange30 !== null ||
    competitors.some((c) => lineChange(lineForCompetitor(trend30?.lines, c)) !== null);

  return (
    <div>
      <div
        ref={entranceRef}
        className={cx(
          // Approved `.wrap` for this screen: gap 22px and padding
          // `26px 32px 52px` (Signal Competitors.html). The shell <main>
          // already supplies the base `.wrap` padding (20px top, 14px
          // bottom), so the negative margins neutralise it and this page's
          // own padding decides the offset, the same way WorkspacePageFrame
          // does it. Without this the page ran on a 16px rhythm and every
          // section below the hero sat ~50px per section above its approved
          // position.
          "flex flex-col gap-[22px] pb-[52px] md:-mt-5 md:-mb-3.5 md:pt-[26px]",
          locked && "pointer-events-none select-none blur-[7px]"
        )}
      >
        <div className="relative flex items-center gap-[26px] overflow-hidden rounded-[22px] border-0 bg-white px-7 py-6 before:absolute before:top-0 before:bottom-0 before:left-0 before:w-1 before:bg-(image:--grad) before:content-[''] max-md:flex-col max-md:items-stretch max-md:p-5">
          {rankOverall !== null ? (
            <div
              data-testid="comp-rank-badge"
              className="w-[132px] flex-none rounded-[14px] border-0 bg-[#EEF1F6] px-0 py-4 text-center"
            >
              <div
                className="font-(family-name:--disp) text-[44px] font-black leading-none tracking-[-0.03em]"
                data-signal-enter="count"
                data-signal-count={rankOverall === null ? undefined : ordinalRank(rankOverall)}
              >
                {ordinalRank(rankOverall)}
              </div>
              <small className="mt-1.5 block font-mono text-[10px] uppercase tracking-[0.1em] text-(--t-3)">
                {t("signalCompetitors.hero.ofTracked", { total: trackedCount })}
              </small>
            </div>
          ) : null}
          <div className="min-w-0 flex-1">
            {/* `.hmeta .eyebrow` is mono in the approved design; rendering it
                in the body font made the block 1px shorter than the approved
                one and shifted the headline and intro under it. */}
            <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-(--purple)">
              {t("signalCompetitors.hero.eyebrow")}
            </div>
            <h1 className="mt-2 mb-1.5 font-(family-name:--disp) text-[28px] font-black tracking-[-0.02em]">
              {rankOverall !== null
                ? t("signalCompetitors.hero.youRank", { rank: ordinalRank(rankOverall) })
                : t("signalCompetitors.hero.title")}
            </h1>
            <p className="m-0 max-w-[600px] text-[14px] leading-[1.5] text-(--t-2)">
              {t("signalCompetitors.hero.intro")}
            </p>
          </div>
          {/* The approved `.gap` card is 250px wide with a larger type scale,
              which is also the width that makes its status line fit on two
              lines and the whole hero exactly the approved 180px (measured:
              English divergence 26.44% -> 23.00%). It is NOT adopted here: at
              250px the headline column narrows to the approved 660px, where
              our Arabic headline wraps to a second line (the approved mockup's
              own Arabic for this headline is materially shorter) and the Arabic
              figure regresses to 37.25%. Closing that needs an Arabic copy
              decision, not a layout one, so the card keeps its 180px width and
              the hero stays 7px taller than the approved one. Reported on
              SIGV2-1037. */}
          {leader && projectOverall !== null && leaderScore !== null ? (
            <div
              data-testid="comp-gap-card"
              className="w-[180px] flex-none rounded-[14px] border-0 bg-[#EEF1F6] px-4 py-4"
            >
              <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-(--t-3)">
                {t("signalCompetitors.hero.gapLabel")}
              </div>
              <div className="mt-1.5 flex items-center gap-2 font-(family-name:--disp) text-[24px] font-black tracking-[-0.02em]">
                <span>{projectOverall}</span>
                <span className="text-(--t-3) rtl:-scale-x-100">→</span>
                <span className="text-(--purple)">{leaderScore}</span>
              </div>
              {/* The approved `.gs` carries no line-height override, so it
                  renders at the normal ratio; the 1.4 here added ~2px a line
                  and, on the third line this card's longer status sentence
                  needs, pushed the card past the approved 130px and the hero
                  past the approved 180px. */}
              <div className="mt-1 text-[11.5px] text-(--t-3)">
                {(() => {
                  const leaderChange = lineChange(lineForCompetitor(trend30?.lines, leader));
                  if (projectChange30 !== null && leaderChange !== null) {
                    const closing = projectChange30 - leaderChange;
                    return closing >= 0
                      ? t("signalCompetitors.hero.gapClosing", {
                          pts: Math.abs(Math.round(closing)),
                          name: leader.display_name,
                        })
                      : t("signalCompetitors.hero.gapWidening", {
                          pts: Math.abs(Math.round(closing)),
                          name: leader.display_name,
                        });
                  }
                  return t("signalCompetitors.hero.gapLeader", {
                    name: leader.display_name,
                  });
                })()}
              </div>
            </div>
          ) : null}
        </div>

        {!locked && hasCompetitors ? (
          <>
            <div className="flex items-center gap-3 md:mt-[26px] md:mb-[14px] max-md:min-w-0 max-md:flex-wrap max-md:items-start">
              <h2 className="m-0 whitespace-nowrap font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em] max-md:min-w-0 max-md:whitespace-normal">
                {t("signalCompetitors.chart.heading")}
              </h2>
              <span className="h-4 w-px flex-none bg-(--line-2)" />
              <span
                data-chart-caption
                className="whitespace-nowrap font-mono text-[11px] tracking-[0.05em] text-(--t-3) max-md:w-full max-md:whitespace-normal"
              >
                {/* Approved caption wording: "blended AIO + SEO · last 6
                    months". The metric half is the approved phrase for the
                    Blended series; the window half names the window the
                    trends endpoint actually returned (30d|90d|1y|all - there
                    is no six-month window to request), so it reads
                    "last 12 months" and that half stays divergent. */}
                {t("signalCompetitors.chart.mini", {
                  metric: t(`signalCompetitors.chart.captionMetric.${chartMetric}`),
                  window: t("signalCompetitors.chart.window1y"),
                })}
              </span>
            </div>
            <div className="rounded-[22px] border-0 bg-white px-6 pb-[18px] pt-[22px]">
              <div className="mb-3.5 flex items-center gap-4 max-md:flex-wrap">
                <div
                  data-testid="comp-chart-legend"
                  className="flex items-center gap-[18px] max-md:flex-wrap"
                >
                  {(chartTrend?.lines ?? []).map((line, idx) => (
                    <span
                      key={line.key}
                      className="flex items-center gap-[7px] text-[12.5px] font-semibold"
                    >
                      <i
                        className="h-[9px] w-[9px] rounded-[3px]"
                        style={{
                          background: line.is_project
                            ? "var(--purple)"
                            : LINE_COLORS[(idx - 1 + LINE_COLORS.length) % LINE_COLORS.length],
                        }}
                      />
                      {line.is_project
                        ? t("signalCompetitors.chart.youLine", {
                            name: project?.name || t("signalCompetitors.scores.you"),
                          })
                        : line.label}
                    </span>
                  ))}
                </div>
                <div className="inline-flex gap-[2px] rounded-[9px] border-0 bg-[#EEF1F6] p-[3px] ltr:ml-auto rtl:mr-auto ltr:[direction:ltr]">
                  {CHART_METRICS.map((metric) => (
                    <button
                      key={metric}
                      type="button"
                      aria-pressed={chartMetric === metric}
                      className={cx(
                        "cursor-pointer rounded-[6px] border-none px-3 py-1.5 font-(family-name:--body-font) text-[12.5px] font-semibold",
                        chartMetric === metric
                          ? "bg-(--ink) text-white"
                          : "bg-transparent text-(--t-2)"
                      )}
                      onClick={() => setChartMetric(metric)}
                    >
                      {t(`signalCompetitors.chart.metric.${metric}`)}
                    </button>
                  ))}
                </div>
              </div>
              {(() => {
                const lines = chartTrend?.lines ?? [];
                const allValues = lines.flatMap((line) =>
                  line.points
                    .map((p) => p.value)
                    .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
                );
                if (allValues.length === 0) {
                  return (
                    <div className="py-10 text-center text-[12.5px] text-(--t-3)">
                      {t("signalCompetitors.chart.unmeasured")}
                    </div>
                  );
                }
                let min = Math.floor(Math.min(...allValues) / 10) * 10;
                let max = Math.ceil(Math.max(...allValues) / 10) * 10;
                if (max - min < 10) {
                  min -= 5;
                  max += 5;
                }
                const step = Math.max(10, Math.ceil((max - min) / 50) * 10);
                const gridValues: number[] = [];
                for (let v = min; v <= max; v += step) gridValues.push(v);
                const y = (v: number) => 230 - ((v - min) / (max - min)) * 200;
                const anchor =
                  lines.reduce((a, b) => (b.points.length > a.points.length ? b : a)).points ?? [];
                const labelEvery = Math.max(1, Math.ceil(anchor.length / 6));
                const monthFmt = new Intl.DateTimeFormat(i18n.language, { month: "short" });
                return (
                  <svg
                    data-testid="comp-trend-chart"
                    viewBox="0 0 920 280"
                    preserveAspectRatio="none"
                    aria-hidden="true"
                    className="block h-auto w-full overflow-visible"
                  >
                    {gridValues.map((v) => (
                      <g key={v}>
                        <line
                          x1={60}
                          y1={y(v)}
                          x2={880}
                          y2={y(v)}
                          stroke="var(--line-2)"
                          strokeWidth={1}
                        />
                        <text
                          x={44}
                          y={y(v) + 4}
                          textAnchor="end"
                          className="fill-(--t-3) font-mono text-[10px]"
                        >
                          {v}
                        </text>
                      </g>
                    ))}
                    {anchor.map((point, idx) =>
                      idx % labelEvery === 0 && point.date ? (
                        <text
                          key={`${point.date}-${idx}`}
                          x={60 + (idx * 820) / Math.max(1, anchor.length - 1)}
                          y={258}
                          textAnchor="middle"
                          className="fill-(--t-3) font-mono text-[10px]"
                        >
                          {monthFmt.format(new Date(point.date))}
                        </text>
                      ) : null
                    )}
                    {lines.map((line, lineIdx) => {
                      const denom = Math.max(1, line.points.length - 1);
                      const pts = line.points
                        .map((p, i) =>
                          typeof p.value === "number"
                            ? `${60 + (i * 820) / denom},${y(p.value)}`
                            : null
                        )
                        .filter(Boolean)
                        .join(" ");
                      const last = [...line.points]
                        .reverse()
                        .find((p) => typeof p.value === "number");
                      const color = line.is_project
                        ? "var(--purple)"
                        : LINE_COLORS[(lineIdx - 1 + LINE_COLORS.length) % LINE_COLORS.length];
                      return (
                        <g key={line.key}>
                          <polyline
                            points={pts}
                            fill="none"
                            stroke={color}
                            strokeWidth={line.is_project ? 3.5 : 2.5}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          {last ? (
                            <circle
                              cx={60 + (line.points.indexOf(last) * 820) / denom}
                              cy={y(last.value as number)}
                              r={line.is_project ? 5 : 4.5}
                              fill={color}
                              stroke="var(--panel)"
                              strokeWidth={2}
                            />
                          ) : null}
                        </g>
                      );
                    })}
                  </svg>
                );
              })()}
            </div>
          </>
        ) : null}

        {!locked && hasCompetitors ? (
          <>
            <div className="flex items-center gap-3 md:mt-[26px] md:mb-[14px] max-md:min-w-0 max-md:flex-wrap max-md:items-start">
              <h2 className="m-0 whitespace-nowrap font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em] max-md:min-w-0 max-md:whitespace-normal">
                {t("signalCompetitors.board.heading")}
              </h2>
              <span className="h-4 w-px flex-none bg-(--line-2)" />
              <span className="whitespace-nowrap font-mono text-[11px] tracking-[0.05em] text-(--t-3) max-md:w-full max-md:whitespace-normal">
                {t("signalCompetitors.board.sub")}
              </span>
            </div>
            <div
              className="rounded-[22px] border-0 bg-white max-md:max-w-full max-md:overflow-x-auto max-md:overscroll-x-contain"
              role="region"
              aria-label={t("signalCompetitors.scores.regionLabel")}
              tabIndex={0}
            >
              <table className="w-full border-collapse max-md:min-w-[720px] [&_thead_th]:border-b [&_thead_th]:border-b-(--line) [&_thead_th]:px-[22px] [&_thead_th]:py-[13px] [&_thead_th]:text-left [&_thead_th]:font-mono [&_thead_th]:text-[10.5px] [&_thead_th]:font-normal [&_thead_th]:uppercase [&_thead_th]:tracking-[0.06em] [&_thead_th]:text-(--t-3) [&_tbody_td]:border-b [&_tbody_td]:border-b-(--line-2) [&_tbody_td]:px-[22px] [&_tbody_td]:py-[15px] [&_tbody_td]:text-[13.5px] [&_tbody_tr:last-child_td]:border-b-0">
                <thead>
                  <tr>
                    <th className="w-[34px]" />
                    <th>{t("signalCompetitors.scores.company")}</th>
                    <th className="text-right">{t("signalCompetitors.metric.aio")}</th>
                    {/* The approved leaderboard head reads AIO / SEO, and this
                        page already says SEO on the chart's own toggle, so the
                        column takes the approved label rather than the prose
                        word "Search" the card copy uses. */}
                    <th className="text-right">{t("signalCompetitors.board.seoColumn")}</th>
                    <th className="w-[200px] text-right">
                      {t("signalCompetitors.metric.visibility")}
                    </th>
                    <th className="text-right">
                      {has30dHistory
                        ? t("signalCompetitors.board.thirtyDay")
                        : t("signalCompetitors.board.gapVsYou")}
                    </th>
                    <th className="w-[34px]" />
                  </tr>
                </thead>
                <tbody>
                  {leaderboardRows.map((row, idx) => {
                    const change30 = row.isProject
                      ? projectChange30
                      : row.competitor
                        ? lineChange(lineForCompetitor(trend30?.lines, row.competitor))
                        : null;
                    return (
                      <tr
                        key={row.key}
                        className={cx(
                          row.isProject &&
                            "bg-[linear-gradient(90deg,var(--purple-a5),var(--blue-a3))]"
                        )}
                      >
                        <td
                          className={cx(
                            "font-(family-name:--disp) text-[18px] font-black text-(--t-3)",
                            row.isProject && "text-(--purple)"
                          )}
                        >
                          {idx + 1}
                        </td>
                        <td>
                          <div className="flex items-center gap-3">
                            <div
                              className={cx(
                                "flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[9px] font-(family-name:--disp) text-[14px] font-bold text-white",
                                row.isProject ? "bg-(image:--grad)" : "bg-(--ink)"
                              )}
                            >
                              {row.name.charAt(0).toUpperCase()}
                            </div>
                            <div className="font-(family-name:--disp) text-[14.5px] font-bold tracking-[-0.01em]">
                              {row.name}
                              {row.isProject ? (
                                <span className="ml-0.5 rounded-[5px] bg-(--ink) px-1.5 py-0.5 text-[9.5px] tracking-[0.06em] text-white">
                                  {t("signalCompetitors.scores.youBadge")}
                                </span>
                              ) : (
                                <small className="block font-mono text-[11.5px] font-normal text-(--t-3)">
                                  {row.sub}
                                </small>
                              )}
                            </div>
                          </div>
                        </td>
                        <td
                          className={cx(
                            "text-right font-(family-name:--disp) text-[16px]! font-extrabold tracking-[-0.01em]",
                            row.isProject ? "text-(--purple)" : "text-(--blue)"
                          )}
                        >
                          {row.aio ?? "-"}
                        </td>
                        <td
                          className={cx(
                            "text-right font-(family-name:--disp) text-[16px]! font-extrabold tracking-[-0.01em]",
                            row.isProject ? "text-(--purple)" : "text-(--blue)"
                          )}
                        >
                          {row.seo ?? "-"}
                        </td>
                        <td className="text-right">
                          {row.visibility !== null ? (
                            <div className="flex items-center justify-end gap-2.5">
                              <div className="h-1.5 w-[70px] overflow-hidden rounded-[999px] bg-(--line)">
                                <i
                                  className="block h-full w-(--vw) origin-left rounded-[999px] bg-(image:--grad) rtl:origin-right"
                                  data-signal-enter="bar"
                                  style={{ "--vw": `${row.visibility}%` } as React.CSSProperties}
                                />
                              </div>
                              <b>{row.visibility}</b>
                            </div>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td className="text-right">
                          {has30dHistory ? (
                            change30 === null ? (
                              <span className="text-[12px] font-medium text-(--t-3)">-</span>
                            ) : change30 > 0 ? (
                              <span className="font-mono text-[12px] font-medium text-(--good)">
                                ↗ +{Math.round(change30)}
                              </span>
                            ) : change30 < 0 ? (
                              <span className="font-mono text-[12px] font-medium text-(--bad)">
                                ↘ {Math.round(change30)}
                              </span>
                            ) : (
                              <span className="font-mono text-[12px] font-medium text-(--t-3)">
                                {t("signalCompetitors.board.hold")}
                              </span>
                            )
                          ) : row.isProject ? (
                            <span className="text-[12px] font-medium text-(--t-3)">-</span>
                          ) : row.delta === null ? (
                            <span className="text-[12px] font-medium text-(--t-3)">-</span>
                          ) : (
                            <span
                              className={cx(
                                "text-[12px] font-medium",
                                // delta = project - competitor: positive is us ahead.
                                row.delta > 0
                                  ? "text-(--good)"
                                  : row.delta < 0
                                    ? "text-(--bad)"
                                    : "text-(--t-3)"
                              )}
                            >
                              {row.delta === 0
                                ? t("signalCompetitors.scores.even")
                                : `${row.delta > 0 ? "+" : ""}${Math.round(row.delta)}`}
                            </span>
                          )}
                        </td>
                        <td className="text-right">
                          {!locked && row.competitor ? (
                            <button
                              type="button"
                              aria-label={t("signalCompetitors.card.remove", {
                                name: row.competitor.display_name,
                              })}
                              disabled={removingId === row.competitor.id}
                              onClick={() => void handleRemove(row.competitor!.id)}
                              className="cursor-pointer border-current bg-transparent p-1 text-(--t-3)"
                            >
                              <svg
                                width="16"
                                height="16"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                              >
                                <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6" />
                              </svg>
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}

        {/* Section order follows the approved page: position, trend,
            leaderboard. The approved page's fourth section, the head-to-head
            block against the leader, is retired (SIGV2-1174): none of its six
            metrics had a source, and measuring the three per-engine mention
            rows would mean running every tracked competitor through the
            project's whole prompt set, so the cost scales with
            competitors x prompts with no cap. Scoping a version we can afford
            to measure is backlogged. The two sections below - the
            question-level evidence and the measured gaps - have no counterpart
            on the approved page, so they come after the approved ones rather
            than between them. They used to sit between the chart and the
            leaderboard, which pushed every approved section out of its approved
            position for the sake of content the design never had. */}
        <div className="flex items-center gap-3 md:mt-[26px] md:mb-[14px] max-md:min-w-0 max-md:flex-wrap max-md:items-start">
          <h2 className="m-0 whitespace-nowrap font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em] max-md:min-w-0 max-md:whitespace-normal">
            {t("signalCompetitors.wins.heading")}
          </h2>
          <span className="h-4 w-px flex-none bg-(--line-2)" />
          <span className="whitespace-nowrap font-mono text-[11px] tracking-[0.05em] text-(--t-3) max-md:w-full max-md:whitespace-normal">
            {t("signalCompetitors.wins.sub")}
          </span>
        </div>

        {!locked && !loadingCompetitive && unmeasured.length > 0 ? (
          <div className="flex flex-wrap items-center gap-3 rounded-[22px] border-0 bg-white px-[15px] py-[10px]">
            <span className="text-[12.5px] leading-[1.5] text-(--t-2)">
              {unmeasured.some((c) => c.latest_status === "pending")
                ? t("signalCompetitors.benchmark.running")
                : t("signalCompetitors.benchmark.noneRan", {
                    names: unmeasured.map((c) => c.display_name).join(", "),
                  })}
            </span>
            {latestAudit ? (
              <button
                type="button"
                className="inline-flex h-[30px] cursor-pointer items-center gap-1.5 rounded-(--r-sm) border border-(--ink) bg-(--ink) px-[11px] font-(family-name:--body-font) text-[12px] font-semibold text-(--panel) hover:bg-black disabled:cursor-not-allowed disabled:opacity-50"
                disabled={benchmarkBusy}
                onClick={() => void runBenchmark()}
              >
                {benchmarkBusy
                  ? t("signalCompetitors.benchmark.busy")
                  : t("signalCompetitors.benchmark.cta")}
              </button>
            ) : null}
          </div>
        ) : null}

        {loadingCompetitive ? (
          <div
            role="status"
            aria-label={t("signalCompetitors.state.loading")}
            className="flex flex-col gap-3"
          >
            <SkelCard />
            <SkelCard />
          </div>
        ) : !hasCompetitors ? (
          <div className="flex flex-col items-center gap-3 rounded-[22px] border-0 bg-white px-6 py-[22px] text-center text-[13px] text-(--t-2)">
            <span>{t("signalCompetitors.empty.noCompetitors")}</span>
            {!locked ? (
              <button
                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                onClick={() => setAddOpen(true)}
              >
                {t("signalCompetitors.add.button")}
              </button>
            ) : null}
          </div>
        ) : !report ? (
          <div className="rounded-[22px] border-0 bg-white p-6">
            <span>{t("signalCompetitors.empty.noCheck")}</span>
          </div>
        ) : !hasComparisons ? (
          <div className="rounded-[22px] border-0 bg-white p-6">
            <span>{t("signalCompetitors.empty.noComparisons")}</span>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {competitors.map((competitor) => {
                const summary = winsByCompetitor.get(competitor.id);
                const wins = summary?.wins ?? 0;
                const considered = summary?.considered ?? 0;
                const questions = summary?.questions ?? [];
                const gapReason = gapReasonByCompetitor.get(competitor.id);
                const scores = competitor.latest_scores;
                const delta = analysisByCompetitor.get(competitor.id)?.delta.overall ?? null;
                const regionId = `competitor-wins-${competitor.id}`;
                const isExpanded = expandedCompetitorId === competitor.id;

                return (
                  <div
                    className="rounded-[22px] border-0 bg-white px-5 py-[18px]"
                    key={competitor.id}
                  >
                    <div className="mb-3.5 flex items-center gap-2.5">
                      <div className="flex items-center gap-3">
                        <div className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[9px] font-(family-name:--disp) text-[14px] font-bold text-white bg-(--ink)">
                          {competitor.display_name.charAt(0).toUpperCase()}
                        </div>
                        <div className="font-(family-name:--disp) text-[14.5px] font-bold tracking-[-0.01em]">
                          {competitor.display_name}
                          <small className="block text-[11.5px] font-normal text-(--t-3)">
                            {competitor.normalized_domain}
                          </small>
                        </div>
                      </div>
                      {!locked ? (
                        <button
                          type="button"
                          aria-label={t("signalCompetitors.card.remove", {
                            name: competitor.display_name,
                          })}
                          disabled={removingId === competitor.id}
                          onClick={() => void handleRemove(competitor.id)}
                          className="cursor-pointer border-current bg-transparent p-1 text-(--t-3)"
                        >
                          <svg
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                          >
                            <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6" />
                          </svg>
                        </button>
                      ) : null}
                    </div>

                    {competitor.latest_status !== "succeeded" ? (
                      <p className="mt-1 mb-0 text-[12px] leading-[1.4] text-(--t-3)">
                        {competitor.latest_status === "pending"
                          ? t("signalCompetitors.benchmark.statusPending")
                          : competitor.latest_status === "failed"
                            ? t("signalCompetitors.benchmark.statusFailed", {
                                reason: competitor.latest_failure_reason ?? "",
                              })
                            : t("signalCompetitors.benchmark.statusNotStarted")}
                      </p>
                    ) : null}

                    <p className="mt-2 mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      {considered === 0
                        ? t("signalCompetitors.card.notAssessed")
                        : wins > 0
                          ? t("signalCompetitors.card.winsStatement", {
                              wins,
                              total: considered,
                              count: wins,
                            })
                          : t("signalCompetitors.card.noWins", { total: considered })}
                    </p>

                    {gapReason ? (
                      <p className="mt-1 text-[12px] text-(--t-3)">
                        {t("signalCompetitors.card.aheadReason", {
                          metric: t(
                            GAP_METRIC_LABEL_KEY[gapReason.metric] ??
                              "signalCompetitors.metric.other"
                          ),
                          reason: gapReason.reason,
                        })}
                      </p>
                    ) : null}

                    <p className="mt-1 text-[12px] text-(--t-3)">
                      {t("signalCompetitors.card.scores", {
                        search: roundOrNull(scores.seo) ?? "-",
                        visibility: roundOrNull(scores.overall) ?? "-",
                        gap: delta === null ? "-" : Math.round(delta),
                      })}
                    </p>

                    {questions.length > 0 ? (
                      <>
                        <button
                          type="button"
                          aria-expanded={isExpanded}
                          aria-controls={regionId}
                          onClick={() =>
                            setExpandedCompetitorId((current) =>
                              current === competitor.id ? null : competitor.id
                            )
                          }
                          className="mt-2 cursor-pointer bg-transparent text-[12px] text-(--purple) underline underline-offset-2"
                        >
                          {isExpanded
                            ? t("signalCompetitors.card.hideQuestions")
                            : t("signalCompetitors.card.showQuestions")}
                        </button>
                        {isExpanded ? (
                          <div id={regionId} role="region" className="mt-2">
                            {questions.map((question) => {
                              const evidenceDate = formatEvidenceDate(question.timestamp);
                              return (
                                <div
                                  className="flex items-center gap-3.5 border-t border-t-(--line-2) py-[11px] first-of-type:border-t-0"
                                  key={question.query}
                                >
                                  <div className="flex-1 text-[13px] text-(--t-2)">
                                    {question.query}
                                  </div>
                                  {question.excerpt ? (
                                    <p className="mt-1 text-[12px] text-(--t-3)">
                                      {question.excerpt}
                                    </p>
                                  ) : null}
                                  {evidenceDate ? (
                                    <p className="mt-1 text-[12px] text-(--t-3)">
                                      {t("signalCompetitors.card.answerFrom", {
                                        date: evidenceDate,
                                      })}
                                    </p>
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                );
              })}
            </div>

            <div className="rounded-[22px] border-0 bg-white p-4">
              {questionWins.nobodyNamed > 0 ? (
                <p className="text-[12px] text-(--t-3)">
                  {t("signalCompetitors.summary.nobodyNamed", {
                    count: questionWins.nobodyNamed,
                  })}
                </p>
              ) : null}
              {questionWins.notMeasured > 0 ? (
                <p className="text-[12px] text-(--t-3)">
                  {t("signalCompetitors.summary.notMeasured", { count: questionWins.notMeasured })}
                </p>
              ) : null}
              {questionWins.unattributedWins > 0 ? (
                <p className="text-[12px] text-(--t-3)">
                  {t("signalCompetitors.summary.unattributed", {
                    count: questionWins.unattributedWins,
                  })}
                </p>
              ) : null}
            </div>
          </>
        )}

        {/* The measured gaps are the one place on this screen that may claim
            "Behind" (SIGV2-1116): every row carries a real project_score and
            competitor_score from the gaps feed, so the verdict has evidence
            under it. Nothing else here may assert a standing. */}
        {!locked && gaps.length > 0 ? (
          <>
            <div className="flex items-center gap-3 md:mt-[26px] md:mb-[14px] max-md:min-w-0 max-md:flex-wrap max-md:items-start">
              <h2 className="m-0 whitespace-nowrap font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em] max-md:min-w-0 max-md:whitespace-normal">
                {t("signalCompetitors.gaps.heading")}
              </h2>
              <span className="h-4 w-px flex-none bg-(--line-2)" />
              <span className="whitespace-nowrap font-mono text-[11px] tracking-[0.05em] text-(--t-3) max-md:w-full max-md:whitespace-normal">
                {t("signalCompetitors.gaps.sub")}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {Array.from(
                gaps.reduce((map, gap) => {
                  const list = map.get(gap.competitor_name) ?? [];
                  list.push(gap);
                  map.set(gap.competitor_name, list);
                  return map;
                }, new Map<string, ProjectCompetitiveGapItem[]>())
              )
                .sort((a, b) => b[1].length - a[1].length)
                .slice(0, 2)
                .map(([competitorName, items]) => (
                  <div
                    className="rounded-[22px] border-0 bg-white px-5 py-[18px]"
                    key={competitorName}
                  >
                    <div className="mb-3.5 flex items-center gap-2.5">
                      <span className="font-(family-name:--disp) text-[14px] font-bold">
                        {t("signalCompetitors.gaps.cardTitle", { name: competitorName })}
                      </span>
                      <span className="ml-auto rounded-md bg-(--bad-s) px-2 py-[3px] text-[10px] uppercase tracking-[0.05em] text-(--bad)">
                        {t("signalCompetitors.gaps.badge")}
                      </span>
                    </div>
                    {items.map((gap) => (
                      <div
                        className="flex items-center gap-3.5 border-t border-t-(--line-2) py-[11px] first-of-type:border-t-0"
                        key={`${gap.competitor_id}-${gap.metric}`}
                      >
                        <div className="flex-1 text-[13px] text-(--t-2)">
                          {t(GAP_METRIC_LABEL_KEY[gap.metric] ?? "signalCompetitors.metric.other")}{" "}
                          · {gap.reason}
                        </div>
                        <div className="flex w-[220px] flex-none items-center gap-[9px]">
                          <div className="flex-1">
                            <div className="mb-1 flex justify-between text-[10.5px] text-(--t-3)">
                              <span>
                                {t("signalCompetitors.gaps.you")}{" "}
                                <b className="text-(--t-1)">{Math.round(gap.project_score)}</b>
                              </span>
                              <span>
                                {t("signalCompetitors.gaps.them")}{" "}
                                <b className="text-(--t-1)">{Math.round(gap.competitor_score)}</b>
                              </span>
                            </div>
                            <div className="h-1.5 overflow-hidden rounded-[999px] bg-(--line)">
                              <i
                                className="block h-full w-(--bw) origin-left rounded-[999px] bg-(--purple) rtl:origin-right"
                                data-signal-enter="bar"
                                style={
                                  {
                                    "--bw": `${Math.min(100, Math.round(gap.competitor_score))}%`,
                                  } as React.CSSProperties
                                }
                              />
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
            </div>
          </>
        ) : null}
      </div>

      {locked ? (
        <SignalUpgradeGate
          open={upgradeGateOpen}
          onClose={() => setUpgradeGateOpen(false)}
          title={t("signalCompetitors.gate.title")}
          description={t("signalCompetitors.gate.description")}
          planLabel={competitorLock.requiredPlanLabel}
          upgradeHref={competitorLock.href}
          upgradeLabel={competitorLock.ctaLabel}
          fallbackHref={projectId ? base : "/dashboard"}
          // The page behind is blurred and inert while locked, so dismissing the
          // gate would leave the user stuck on an unreadable page.
          dismissible={false}
        >
          <div>
            <b className="text-(--t-1)">{t("signalCompetitors.gate.featureTitle")}</b>
            <p>{t("signalCompetitors.gate.featureBody")}</p>
          </div>
        </SignalUpgradeGate>
      ) : null}

      <SignalAddCompetitorModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        projectId={projectId}
        getAuthHeaders={getAuthHeaders}
        onCreated={() => {
          toast.success(t("signalCompetitors.toast.added"));
          void loadCompetitive();
        }}
      />
    </div>
  );
}
