"use client";

// Rebuilt 1:1 with /Users/user/signal-MVP/Signal AIO Detail.html: breadcrumb
// top bar, hero ring, and the approved four tabs (Improve, Search types,
// By engine, Prompts). Wired to real audit data (useProjectLatestAudit) and
// the visibility summary feed; anything the feeds do not produce is rendered
// as an explicit unmeasured state rather than a plausible number.
import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";
import SignalLockCard from "@/components/signal/SignalLockCard";
import { LockedActPreview } from "@/components/signal/SignalLockedPlanPreview";

import { useAuth } from "@/components/auth/custom-auth";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { useSignalEntrance } from "@/hooks/useSignalChartMotion";
import { isAuditResult } from "@/types/auditResult";
import {
  deriveRecommendations,
  normalizeLatestAuditReport,
  sortRecommendations,
} from "@/lib/deriveRecommendations";
import {
  getSearchTypes,
  isMeasuredSearchType,
  type FixSource,
  type ResolvedLevel,
  type SearchType,
} from "@/lib/reportAdapters";
import { fixSourceLabelKeys } from "@/lib/fixSource";
import { resolveAdvisorPlanAccess } from "@/lib/advisorPlanAccess";
import { provenanceByProvider } from "@/lib/visibilityProvenance";
import { cx } from "@/components/ui/utils";
import { fetchVisibilitySummary } from "@/services/monitoringService";
import PromptSetup from "@/components/signal/PromptSetup";
import { useScanPrompts } from "@/hooks/useScanPrompts";
import SignalCrumb from "@/components/signal/SignalCrumb";
import SignalExportMenu from "@/components/signal/SignalExportMenu";
import SignalTabs from "@/components/signal/SignalTabs";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import type { VisibilityProviderBreakdown, VisibilitySummaryResponse } from "@/types/monitoring";
import {
  VISIBILITY_PROVIDER_LABELS,
  isMeasuredVisibilityProvider,
  measuredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";

const RING_C = 2 * Math.PI * 54;

const roundOrNull = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null;

const scoreColor = (n: number): string =>
  n >= 70 ? "var(--good)" : n >= 50 ? "var(--warn)" : "var(--bad)";

type TabId = "improve" | "types" | "engines" | "prompts";
const TABS: TabId[] = ["improve", "types", "engines", "prompts"];

// This page's approved <style> block overrides .sec h2 to 14px/700 and .mini
// to mono 11px ls .05em (the shared rules are 17px/800 and 12.5px body text).
const sectionHeaderCls = "m-0 font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em]";
const miniCls =
  "whitespace-nowrap font-mono text-[11px] tracking-[0.05em] text-(--t-3) max-md:w-full max-md:whitespace-normal";
const unmeasuredCls = "font-mono text-[11px] text-(--t-3)";
const emptyCls =
  "mt-3.5 flex flex-col items-center gap-3 rounded-2xl border border-(--line) bg-(--panel) px-6 py-[22px] text-center text-[13px] text-(--t-2)";
const btnCls =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-(--line-btn-hover) disabled:cursor-not-allowed disabled:opacity-50";
const btnPrimaryCls =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black";

/** signal-MVP `.sec`: heading, `.ln` divider, `.mini`, spacer, action. */
function Sec({ title, mini, action }: { title: string; mini?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-3.5 flex items-center gap-3 max-md:min-w-0 max-md:flex-wrap max-md:items-start">
      <h2 className={sectionHeaderCls}>{title}</h2>
      <span className="h-4 w-px flex-none bg-(--line-2)" />
      {mini ? <span className={miniCls}>{mini}</span> : null}
      <div className="flex-1" />
      {action}
    </div>
  );
}

export default function ProjectAioDetailPage() {
  const { t } = useTranslation();
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const numericProjectId = Number(projectId);
  const base = `/dashboard/projects/${projectId}`;
  const deeperAuditHref = `/dashboard/audit?projectId=${projectId}&tier=smart&tab=overview`;
  const [activeTab, setActiveTab] = useState<TabId>("improve");
  const [open, setOpen] = useState<number | null>(null);
  // SIGV2-1194: the Prompts tab is the manage mode of the approved
  // prompt-setup surface; its own add/edit/remove live inside it.

  // `?tab=` makes a single tab linkable from elsewhere in the product; the
  // overview's "Appearance in AI answers" explanation sends people straight to
  // Prompts, the surface that actually drives that figure (SIGV2-1111). Same
  // contract as AuditWorkspace: an unknown value is ignored, not fatal.
  const searchParams = useSearchParams();
  const requestedTab = searchParams?.get("tab") ?? null;
  useEffect(() => {
    if (requestedTab && (TABS as readonly string[]).includes(requestedTab)) {
      setActiveTab(requestedTab as TabId);
    }
  }, [requestedTab]);

  const { project, latestAudit, loading, error, refetch } = useProjectLatestAudit(projectId, {
    includeFullReport: true,
  });

  const { getToken, isSignedIn } = useAuth();

  // ------------------------------------------------------------------
  // Visibility summary: the only feed that carries per-prompt and
  // per-engine visibility results (plan-gated monitoring data).
  // ------------------------------------------------------------------
  const [summary, setSummary] = useState<VisibilitySummaryResponse | null>(null);
  const [summaryFailed, setSummaryFailed] = useState(false);

  const loadSummary = useCallback(async () => {
    if (!projectId || !isSignedIn) return;
    try {
      const token = await getToken();
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
      setSummary(await fetchVisibilitySummary(projectId, headers));
      setSummaryFailed(false);
    } catch {
      // A missing or refused feed must not take down the score page; both
      // tabs that read it show their own explicit unavailable state.
      setSummary(null);
      setSummaryFailed(true);
    }
  }, [getToken, isSignedIn, projectId]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const promptAuthHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  // The Prompts tab reads the same live project list as scan setup
  // (SIGV2-1194), so the two surfaces can never disagree.
  const promptSetupState = useScanPrompts({
    projectId: Number.isFinite(numericProjectId) ? numericProjectId : undefined,
    isSignedIn: Boolean(isSignedIn),
    getAuthHeaders: promptAuthHeaders,
  });

  const report = useMemo(() => {
    const raw = latestAudit?.full_report;
    return isAuditResult(raw) ? (raw as Record<string, any>) : null;
  }, [latestAudit?.full_report]);

  const score = useMemo(() => {
    const aeo = roundOrNull(
      report?.scores?.aeo ?? project?.latest_aeo_score ?? report?.aeo?.answerability_score
    );
    const geo = roundOrNull(
      report?.scores?.geo ?? project?.latest_geo_score ?? report?.geo?.visibility_index
    );
    const parts = [aeo, geo].filter((v): v is number => typeof v === "number");
    if (parts.length === 0) return null;
    return Math.round(parts.reduce((a, b) => a + b, 0) / parts.length);
  }, [report, project?.latest_aeo_score, project?.latest_geo_score]);

  const heroEntranceRef = useSignalEntrance(
    `hero:${loading ? "loading" : "ready"}:${score ?? "-"}`
  );

  const searchTypes = useMemo<SearchType[]>(() => {
    const canonical = normalizeLatestAuditReport(latestAudit);
    if (canonical) return getSearchTypes(canonical);
    const raw = report?.metadata?.search_types;
    return Array.isArray(raw) ? getSearchTypes({ metadata: { search_types: raw } } as any) : [];
  }, [latestAudit, report]);

  // Recommendation titles are gated content: count them to decide whether the
  // improve panel exists, but only materialise the rows when the plan allows
  // the action plan (see the lockgate below).
  const improveCount = useMemo(() => {
    return deriveRecommendations(latestAudit).filter(
      (r) => r.engines.includes("AEO") || r.engines.includes("GEO")
    ).length;
  }, [latestAudit]);
  const advisorPlan = resolveAdvisorPlanAccess(project);
  // SIGV2-1211: impact is categorical by product rule, and the band is
  // resolved once on the consolidated row (SIGV2-1193), shared with the full
  // action plan, so a fix cannot be rated here and unrated there. A row the
  // audit attached no number to stays unrated rather than defaulting to
  // Medium. The numeric deduction never reaches the row: it measures what the
  // problem costs today, not what fixing it would recover.
  const improve = useMemo(() => {
    if (!advisorPlan.allowed)
      return [] as {
        title: string;
        action: string;
        category: string;
        impact: ResolvedLevel;
        sources: FixSource[];
      }[];
    return sortRecommendations(deriveRecommendations(latestAudit))
      .filter((r) => r.engines.includes("AEO") || r.engines.includes("GEO"))
      .slice(0, 4)
      .map((r) => ({
        title: r.title,
        action: r.description,
        category: r.category,
        // SIGV2-1193: the band is resolved once, on the consolidated row, so
        // this list and the action plan cannot rate the same fix differently.
        impact: r.impactLevel,
        sources: r.sources,
      }));
  }, [latestAudit, advisorPlan.allowed]);

  const hasScore = score !== null;
  // The action plan is a Pro feature (agents action each fix). Gate it off real
  // feature access rather than a demo toggle.

  // ------------------------------------------------------------------
  // Export: the approved `.exp-menu` control (SIGV2-1124). The four PDF
  // variants, their locks and the job panel all live in SignalExportMenu;
  // this page only says which screen it is and what audit to build from.
  // ------------------------------------------------------------------
  const auditId = typeof latestAudit?.id === "number" ? latestAudit.id : null;

  // Approved `.top`: crumb + actions live inside the shared SignalTopBar
  // (registered via the page-header context), never a second row under it.
  const { setHeader } = useWorkspacePageHeader();
  const topCrumb = useMemo(
    () => (
      <SignalCrumb
        items={[
          { label: t("signalAioDetail.crumbHome"), href: base },
          { label: t("signalAioDetail.crumbCurrent") },
        ]}
      />
    ),
    [t, base]
  );
  const topActions = useMemo(
    () => (
      <>
        <SignalExportMenu
          page="aio"
          reportKind="aio"
          auditId={auditId}
          projectId={Number.isFinite(numericProjectId) ? numericProjectId : null}
        />
        <Link href={`${base}/settings`} className={btnPrimaryCls}>
          {t("signalAioDetail.improveSettings")}
        </Link>
      </>
    ),
    [auditId, numericProjectId, t, base]
  );
  useEffect(() => {
    setHeader({ crumb: topCrumb, actions: topActions });
    return () => setHeader(null);
  }, [setHeader, topCrumb, topActions]);

  if (loading) {
    return (
      <div role="status" aria-label="Loading your AI check" className="flex flex-col gap-5">
        <SkelPagehead />
        <SkelCard className="h-[186px]" />
        <SkelCard />
      </div>
    );
  }
  if (error) {
    return (
      <div className="min-w-0">
        <SignalAlert tone="danger" title={t("alerts.errorTitle")}>
          {error}
        </SignalAlert>
        <button type="button" className={`${btnCls} mt-3 min-h-11`} onClick={() => void refetch()}>
          {t("common.tryAgain")}
        </button>
      </div>
    );
  }

  // SIGV2-1215: a withdrawn engine is neither counted nor listed here. A
  // project that selected Copilot while it was offered can still have a
  // breakdown row for it, and this tab is the per-engine surface.
  // SIGV2-1216: nor is an engine this plan has stopped measuring. The count
  // on the tab is a claim about how many engines we measure, so it has to
  // come off the plan's roster rather than off the stored prompt rows.
  const planProviders = summary?.entitlements?.allowed_providers;
  const engineRows = (summary?.provider_breakdown ?? []).filter((row) =>
    isMeasuredVisibilityProvider(row.provider, planProviders)
  );
  const engineCount = engineRows.length
    ? engineRows.length
    : measuredVisibilityProviders(summary?.providers, planProviders).length;
  // SIGV2-1299: the row's label names a consumer engine, so the row also has
  // to say when the answer behind it did not come from that engine.
  const engineSources = summary ? provenanceByProvider(summary) : {};

  const tabCounts: Record<TabId, number> = {
    improve: improveCount,
    types: searchTypes.length,
    engines: engineCount,
    prompts: summary?.queries?.length ?? 0,
  };
  const tabLabels: Record<TabId, string> = {
    improve: t("signalAioDetail.tabImprove"),
    types: t("signalAioDetail.tabTypes"),
    engines: t("signalAioDetail.tabEngines"),
    prompts: t("signalAioDetail.tabPrompts"),
  };

  const summaryLocked = summary?.entitlements?.is_locked === true;
  const visibilityUnavailableReason = summaryFailed
    ? t("signalAioDetail.feedFailed")
    : summaryLocked
      ? t("signalAioDetail.enginesLocked")
      : null;

  return (
    // SIGV2-1036: the approved page's own <style> overrides the shared
    // `.wrap{padding:20px 32px 14px}` to `26px 32px 52px`, and the dashboard
    // shell supplies the shared value, so the built body sits 4px above the
    // approved frame in English. Adding the 6px/38px difference here was
    // measured and reverted: the extra 38px at the bottom pushed this page's
    // Arabic Search-types panel past the shell's min-height, growing the
    // document from 915px to 930px against a 900px approved page and taking
    // aio-detail-tab-types ar from 16.85% to 20.78%, over its budget. The
    // 6px at the top only helps English, because the Arabic hero is 165px in
    // the approved page against 196px here (longer Arabic strings), so the
    // Arabic body already sits below the frame.
    <div className="flex min-w-0 flex-col gap-[22px]">
      <div ref={heroEntranceRef} className="flex flex-col gap-[22px]">
        {/* signal-MVP `.hero` */}
        <div className="relative flex items-center gap-[26px] overflow-hidden rounded-(--r) border border-(--line) bg-(--panel) px-7 py-6 before:absolute before:top-0 before:bottom-0 before:start-0 before:w-1 before:bg-(image:--grad) before:content-[''] max-md:flex-col max-md:items-stretch max-md:p-5">
          <div className="relative h-[132px] w-[132px] flex-none max-md:self-center">
            <svg viewBox="0 0 132 132" className="h-[132px] w-[132px] -rotate-90">
              <defs>
                <linearGradient id="gA" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="var(--blue)" />
                  <stop offset="1" stopColor="var(--purple)" />
                </linearGradient>
              </defs>
              <circle cx="66" cy="66" r="54" fill="none" stroke="var(--line)" strokeWidth="11" />
              <circle
                cx="66"
                cy="66"
                r="54"
                fill="none"
                stroke="url(#gA)"
                strokeWidth="11"
                strokeLinecap="round"
                strokeDasharray={RING_C}
                strokeDashoffset={RING_C * (1 - (score ?? 0) / 100)}
                data-signal-enter="ring"
              />
            </svg>
            <div className="absolute inset-0 mt-0 flex flex-col items-center justify-center">
              <b
                className="block font-(family-name:--disp) text-[40px] font-black leading-none tracking-[-0.02em]"
                data-signal-enter="count"
                data-signal-count={score ?? undefined}
              >
                {score === null ? (
                  <span className="font-(family-name:--body-font) text-[12px] font-semibold tracking-normal text-(--t-3)">
                    {t("signalOverview.notMeasured")}
                  </span>
                ) : (
                  score
                )}
              </b>
              {score !== null && (
                <small className="text-[10px] uppercase tracking-[0.12em] text-(--t-3)">/100</small>
              )}
            </div>
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] uppercase tracking-[0.14em] text-(--purple)">
              {t("signalAioDetail.eyebrow")}
            </div>
            <h1 className="mt-2 mb-1.5 font-(family-name:--disp) text-[28px] font-black tracking-[-0.02em]">
              {t("signalAioDetail.heroTitle")}
            </h1>
            <p className="m-0 max-w-[560px] text-[14px] leading-[1.5] text-(--t-2)">
              {t("signalAioDetail.heroCopy")}
            </p>
          </div>
          <div className="w-[250px] flex-none rounded-[12px] border border-(--line) bg-(--paper) px-[18px] py-4 max-md:w-full">
            <div className="text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              {t("signalAioDetail.currentScore")}
            </div>
            <div className="mt-2 mb-1 flex items-baseline gap-2">
              <span className="font-(family-name:--disp) text-[30px] font-black tracking-[-0.02em]">
                {score === null ? (
                  <span className="font-(family-name:--body-font) text-[12px] font-semibold tracking-normal text-(--t-3)">
                    {t("signalOverview.notMeasured")}
                  </span>
                ) : (
                  score
                )}
              </span>
            </div>
            <div className="text-[12.5px] text-(--t-2)">
              {project?.score_targets?.aio == null
                ? t("signalAioDetail.noTargets")
                : project.score_targets.aio.gap === null
                  ? t("signalAioDetail.targetUnmeasured", {
                      target: project.score_targets.aio.target,
                    })
                  : project.score_targets.aio.gap === 0
                    ? t("signalAioDetail.atTarget", {
                        target: project.score_targets.aio.target,
                      })
                    : t("signalAioDetail.targetLine", {
                        target: project.score_targets.aio.target,
                        gap: Math.round(project.score_targets.aio.gap),
                      })}
            </div>
          </div>
        </div>

        {/* signal-MVP `.tabs`: the approved underline row via SignalTabs. */}
        <SignalTabs
          tabs={TABS.map((tab) => ({ id: tab, label: tabLabels[tab], count: tabCounts[tab] }))}
          activeId={activeTab}
          onChange={(id) => setActiveTab(id as TabId)}
        />

        {/* IMPROVE */}
        <div
          role="tabpanel"
          id="signal-tabpanel-improve"
          aria-labelledby="signal-tab-improve"
          hidden={activeTab !== "improve"}
        >
          {/* SIGV2-1175: this list and the action plan read disjoint data
              sets (audit findings vs Advisor recommendations), so each names
              its own source and count, and the link names where it actually
              goes rather than implying an expanded version of this list. */}
          <Sec
            title={t("signalAioDetail.improveTitle")}
            mini={
              advisorPlan.allowed
                ? t("signalAioDetail.improveMini", {
                    shown: improve.length,
                    total: improveCount,
                  })
                : t("signalAioDetail.improveMiniLocked", { total: improveCount })
            }
            action={
              <Link
                href={`${base}/fixes`}
                className="inline-flex h-[30px] cursor-pointer items-center gap-2 rounded-lg border border-(--line) bg-(--panel) px-[11px] font-(family-name:--body-font) text-[12px] font-semibold text-(--t-1) hover:border-(--line-btn-hover)"
              >
                {t("signalAioDetail.advisorActionPlan")}
              </Link>
            }
          />
          {improveCount > 0 ? (
            <div className={cx("relative", !advisorPlan.allowed && "grid")}>
              <div
                className={cx(
                  !advisorPlan.allowed &&
                    "col-start-1 row-start-1 pointer-events-none select-none blur-[6px]"
                )}
                aria-hidden={!advisorPlan.allowed || undefined}
              >
                <div className="rounded-(--r) border border-(--line) bg-(--panel)">
                  {!advisorPlan.allowed ? (
                    // Blur is presentation, not authorization: gated rows
                    // must not sit in the DOM, so render the approved .act
                    // anatomy with generic illustrative copy, never the
                    // customer's recommendations.
                    <LockedActPreview accent="purple" />
                  ) : (
                    improve.map((a) => (
                      <div
                        className="flex items-center gap-4 border-t border-t-(--line-2) px-[22px] py-[18px] first:border-t-0"
                        key={a.title}
                      >
                        {/* The approved `.act` row's leading column. It held
                            the "+N PTS" badge; the figure is gone (SIGV2-1211)
                            but the column is the approved row anatomy and is
                            kept, empty, exactly as it already was for a row
                            the audit attached no number to. */}
                        <div className="w-16 flex-none text-center" aria-hidden="true" />
                        <div className="min-w-0 flex-1">
                          <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                            {a.title}
                          </h3>
                          {a.action ? (
                            <p className="mt-[5px] text-[13px] leading-[1.5] text-(--t-2)">
                              {a.action}
                            </p>
                          ) : null}
                          <div className="mt-[9px] flex flex-wrap items-center gap-2">
                            <span className="rounded-[6px] bg-(--purple-a10) px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--purple)">
                              {a.category}
                            </span>
                            {/* SIGV2-1193: one consolidated list, so each row
                                says which channel raised it rather than the
                                list as a whole naming one source. */}
                            {fixSourceLabelKeys(a.sources).map((key) => (
                              <span
                                key={key}
                                className="rounded-[6px] border border-(--line) bg-(--paper) px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--t-3)"
                              >
                                {t(key)}
                              </span>
                            ))}
                            {a.impact.measured ? (
                              <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
                                {t("signalFixes.plan.impactRated", {
                                  level: t(`signalFixes.plan.level.${a.impact.level}`),
                                })}
                              </span>
                            ) : (
                              <span
                                className="rounded-[6px] border border-dashed border-(--line) px-2 py-[3px] text-[10.5px] tracking-[0.04em] text-(--t-3)"
                                title={t("signalFixes.plan.unratedHint")}
                              >
                                {t("signalFixes.plan.impactUnrated")}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div
                className={cx(
                  "relative z-10 col-start-1 row-start-1 items-center justify-center p-4",
                  // SIGV2-1305: an upsell needs a positive refusal, not
                  // silence. `allowed` is false both for a plan that excludes
                  // this and for a payload that never said, and only the
                  // first justifies asking a customer to pay. QA caught a
                  // Standard customer being asked to upgrade for the action
                  // plan their plan grants.
                  //
                  // The blurred content behind this is unchanged: withholding
                  // on an unknown entitlement is the fail-safe direction, and
                  // it was only the demand for money that was unsafe.
                  !advisorPlan.allowed && advisorPlan.resolved ? "flex" : "hidden"
                )}
              >
                <SignalLockCard
                  eyebrow={advisorPlan.requiredPlan ?? ""}
                  title={t("signalFixes.plan.gateTitle")}
                  body={
                    advisorPlan.requiredPlan
                      ? t("signalFixes.plan.gateBodyPlan", { plan: advisorPlan.requiredPlan })
                      : t("signalFixes.plan.gateBody")
                  }
                  ctaLabel={
                    advisorPlan.requiredPlan
                      ? t("signalFixes.plan.gateCtaPlan", { plan: advisorPlan.requiredPlan })
                      : t("signalFixes.plan.gateCta")
                  }
                  ctaHref={advisorPlan.upgradeHref}
                />
              </div>
            </div>
          ) : (
            <div className={emptyCls}>
              <span>
                {hasScore
                  ? t("signalAioDetail.improveEmpty")
                  : t("signalAioDetail.improveEmptyNoScore")}
              </span>
            </div>
          )}
        </div>

        {/* SEARCH TYPES */}
        <div
          role="tabpanel"
          id="signal-tabpanel-types"
          aria-labelledby="signal-tab-types"
          hidden={activeTab !== "types"}
        >
          <Sec title={t("signalAioDetail.typesTitle")} mini={t("signalAioDetail.typesMini")} />
          {searchTypes.length > 0 ? (
            <div className="rounded-(--r) border border-(--line) bg-(--panel)">
              {searchTypes.map((s, i) => {
                // Measured on this project's own AI-engine runs, or nothing.
                // The retired "Estimated" state put an audit sub-score behind
                // this label, which is a different quantity (SIGV2-1105).
                const measured = isMeasuredSearchType(s);
                const stScore = measured ? (s.score as number) : 0;
                return (
                  <div className="border-t border-t-(--line-2) first:border-t-0" key={s.id}>
                    <button
                      type="button"
                      className="flex w-full cursor-pointer items-center gap-3.5 border-current px-[22px] py-4 text-left font-normal hover:bg-(--line-2) focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--purple)"
                      aria-expanded={open === i}
                      onClick={() => setOpen(open === i ? null : i)}
                    >
                      <span
                        className="w-[52px] flex-none font-(family-name:--disp) text-[26px] font-black tracking-[-0.02em] text-(--sc)"
                        style={{ "--sc": scoreColor(stScore) } as React.CSSProperties}
                      >
                        {measured ? s.score : "-"}
                      </span>
                      <span className="flex-1">
                        <span className="block font-(family-name:--disp) text-[14.5px] font-bold">
                          {s.label}
                        </span>
                        <span
                          className={cx(
                            "mt-1 inline-block rounded-[6px] px-2 py-[2px] text-[10.5px]",
                            measured ? "bg-(--good-s) text-(--good)" : "bg-(--line-2) text-(--t-2)"
                          )}
                        >
                          {measured
                            ? t("signalOverview.measured")
                            : t("signalOverview.notMeasured")}
                        </span>
                      </span>
                      <span className="block h-[7px] w-[150px] flex-none overflow-hidden rounded-[999px] bg-(--line)">
                        <i
                          className="block h-full w-(--sw) origin-left rounded-[999px] bg-(--sc) rtl:origin-right"
                          data-signal-enter="bar"
                          style={
                            {
                              "--sw": `${stScore}%`,
                              "--sc": scoreColor(stScore),
                            } as React.CSSProperties
                          }
                        />
                      </span>
                      <svg
                        className={cx(
                          "text-(--t-3) transition-transform duration-200",
                          open === i && "rotate-90"
                        )}
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path d="M9 6l6 6-6 6" />
                      </svg>
                    </button>
                    <div
                      className={cx(
                        "px-[22px] pt-0.5 pb-5 ps-[74px]",
                        open === i ? "block" : "hidden"
                      )}
                    >
                      <div className="mt-3 mb-1.5 text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        {t("signalAioDetail.whyHere")}
                      </div>
                      <p className="m-0 text-[13px] leading-[1.55] text-(--t-2)">
                        {s.insight || t("signalAioDetail.noInsight")}
                      </p>
                      {/* Per-search-type improvement lists have no source: the
                          audit emits global recommendations, not keyed to a
                          type, so this slot names that rather than re-showing
                          the global list under a type heading. */}
                      <div className="mt-4 mb-1.5 text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        {t("signalAioDetail.howImprove")}
                      </div>
                      <p className={unmeasuredCls}>{t("signalAioDetail.typeActionsUnmeasured")}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className={emptyCls}>
              <span>{t("signalAioDetail.typesEmpty")}</span>
              <Link href={deeperAuditHref} className={btnPrimaryCls}>
                {t("signalAioDetail.typesEmptyCta")}
              </Link>
            </div>
          )}
        </div>

        {/* BY ENGINE */}
        <div
          role="tabpanel"
          id="signal-tabpanel-engines"
          aria-labelledby="signal-tab-engines"
          hidden={activeTab !== "engines"}
        >
          <Sec title={t("signalAioDetail.enginesTitle")} />
          {visibilityUnavailableReason ? (
            <div className={emptyCls}>
              <span>{visibilityUnavailableReason}</span>
            </div>
          ) : engineRows.length > 0 ? (
            <div className="rounded-(--r) border border-(--line) bg-(--panel)">
              {engineRows.map((row: VisibilityProviderBreakdown) => (
                <div
                  key={row.provider}
                  className="flex items-center gap-3.5 border-t border-t-(--line-2) px-[22px] py-[14px] first:border-t-0 max-md:flex-wrap"
                >
                  {/* SIGV2-1036, measured and reverted: this row's columns do
                      not follow signal.css `.eng` (`.mb` 30x30 r8 display
                      13/700, `.en` 100px, `.tr` flex:1, `.note` 280px fixed,
                      `.stt` 96px trailing mono 11.5px), and moving them onto
                      it made the gate WORSE on all four variants
                      (aio-detail-tab-engines en 14.72 -> 15.52, ar 15.77 ->
                      16.75, over budget). The reason is `.tr{flex:1}`: it
                      makes the bar ~517px instead of 150px, and this bar is a
                      real visibility score on a good/warn/bad scale while the
                      approved art is a fixed blue-purple gradient at a
                      different fill fraction, so five times more bar means
                      five times more honest-but-divergent pixels. Nothing here
                      is masked. Realigning the columns needs a decision about
                      the bar first; it is not a free layout fix. */}
                  <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-(--line-2) font-mono text-[12px] font-semibold text-(--t-2)">
                    {(VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider).charAt(0)}
                  </span>
                  <span className="w-[140px] flex-none text-[13.5px] font-semibold text-(--t-1) max-md:w-full">
                    {VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider}
                  </span>
                  <span className="block h-[7px] w-[150px] flex-none overflow-hidden rounded-[999px] bg-(--line)">
                    <i
                      className="block h-full w-(--sw) origin-left rounded-[999px] bg-(--sc) rtl:origin-right"
                      data-signal-enter="bar"
                      style={
                        {
                          "--sw": `${row.visibility_score ?? 0}%`,
                          "--sc": scoreColor(row.visibility_score ?? 0),
                        } as React.CSSProperties
                      }
                    />
                  </span>
                  <span className="flex-1 text-[12.5px] text-(--t-2)">
                    {row.completed_checks > 0
                      ? t("signalAioDetail.citedOfChecks", {
                          cited: row.cited_checks,
                          total: row.completed_checks,
                        })
                      : t("signalAioDetail.noCompletedChecks")}
                    {/* SIGV2-1299: a stand-in answer must not sit under a
                        consumer engine label with nothing to distinguish it.
                        Rendered inside the existing note slot rather than as
                        its own column, because the engines tab is already at
                        the edge of its design-comparison budget (see the
                        SIGV2-1036 note above). */}
                    {engineSources[row.provider] === "fallback" ||
                    engineSources[row.provider] === "mixed" ? (
                      <span
                        className="text-(--t-3)"
                        data-testid={`engine-standin-${row.provider}`}
                        title={t("signalAioDetail.engineStandInReason", {
                          engine: VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider,
                        })}
                      >
                        {" · "}
                        {t(
                          engineSources[row.provider] === "mixed"
                            ? "signalAioDetail.engineStandInPartial"
                            : "signalAioDetail.engineStandIn",
                          { engine: VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider }
                        )}
                      </span>
                    ) : null}
                  </span>
                  {/* A provider score is not the design's three-way
                      recommended / mentioned / absent status, and the backend
                      defines no mapping between them, so the status slot is
                      unmeasured rather than thresholded. */}
                  <span
                    className={cx(unmeasuredCls, "flex-none")}
                    title={t("signalAioDetail.statusReason")}
                  >
                    {t("signalAioDetail.statusNotMeasured")}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className={emptyCls}>
              <span>{t("signalAioDetail.enginesEmpty")}</span>
            </div>
          )}
        </div>

        {/* PROMPTS */}
        <div
          role="tabpanel"
          id="signal-tabpanel-prompts"
          aria-labelledby="signal-tab-prompts"
          hidden={activeTab !== "prompts"}
        >
          {/* SIGV2-1194: the approved prompt-setup surface in manage mode.
              The old per-prompt results table is gone; this tab is where the
              prompt set itself is edited (add, reword, remove). */}
          <PromptSetup
            mode="manage"
            state={promptSetupState}
            project={promptSetupState.project}
            getAuthHeaders={promptAuthHeaders}
          />
        </div>
      </div>
    </div>
  );
}
