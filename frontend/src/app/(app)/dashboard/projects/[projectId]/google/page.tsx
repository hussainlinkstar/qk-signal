"use client";

// Rebuilt 1:1 with /Users/user/signal-MVP/Signal SEO Detail.html: breadcrumb
// top bar, hero ring, and the approved four tabs (Improve, Ranking factors,
// Keywords, Pages). Wired to real audit data (useProjectLatestAudit), the SERP
// tracking feed and the Search Console pages feed (SIGV2-1025). Anything the
// feeds do not produce is rendered as an explicit unmeasured state rather than
// a plausible number.
import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/custom-auth";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { useSignalEntrance } from "@/hooks/useSignalChartMotion";
import { isAuditResult } from "@/types/auditResult";
import { deriveRecommendations, sortRecommendations } from "@/lib/deriveRecommendations";
import type { FixSource, ResolvedLevel } from "@/lib/reportAdapters";
import { fixSourceLabelKeys } from "@/lib/fixSource";
import { resolveAdvisorPlanAccess } from "@/lib/advisorPlanAccess";
import { ProjectFeatureBanner } from "@/components/dashboard/ProjectFeatureScaffold";
import { SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";
import SignalLockCard from "@/components/signal/SignalLockCard";
import { LockedActPreview } from "@/components/signal/SignalLockedPlanPreview";
import { cx } from "@/components/ui/utils";
import {
  fetchSearchConsolePages,
  fetchSerpTrackingSummary,
  listTargetKeywords,
} from "@/services/monitoringService";
import SignalAddKeywordModal from "@/components/signal/SignalAddKeywordModal";
import SignalCrumb from "@/components/signal/SignalCrumb";
import SignalExportMenu from "@/components/signal/SignalExportMenu";
import SignalTabs from "@/components/signal/SignalTabs";
import SignalScoreHero from "@/components/signal/SignalScoreHero";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import {
  isSearchConsolePagesPayload,
  type SearchConsolePageRow,
  type SearchConsolePagesResponse,
  type SerpTrackingSummary,
  type TargetKeyword,
} from "@/types/monitoring";

const roundOrNull = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null;

const scoreColor = (n: number): string =>
  n >= 70 ? "var(--good)" : n >= 50 ? "var(--warn)" : "var(--bad)";

const formatNumber = (v: number | null | undefined): string =>
  typeof v === "number" && Number.isFinite(v) ? Math.round(v).toLocaleString() : "-";

const formatPosition = (v: number | null | undefined): string =>
  typeof v === "number" && Number.isFinite(v) && v > 0 ? v.toFixed(1) : "-";

// The five measured components the deterministic scorer emits on report.seo.
// `onpage`, `performance` and `indexing` are deliberately not used here: the
// adapter writes all three from the same seo_score variable, so they render one
// number three times while presenting themselves as three measurements.
const FACTOR_KEYS = [
  "core_web_vitals",
  "technical_seo",
  "onpage_content",
  "eeat_trust",
  "security_accessibility",
] as const;

// Reports written before the component breakdown existed only carry these.
const LEGACY_FACTOR_KEYS = ["onpage", "performance", "indexing"] as const;

type TabId = "improve" | "factors" | "keywords" | "pages";
const TABS: TabId[] = ["improve", "factors", "keywords", "pages"];

// This page's approved <style> block overrides .sec h2 to 14px/700 and .mini
// to mono 11px ls .05em (the shared rules are 17px/800 and 12.5px body text).
const sectionHeaderCls = "m-0 font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em]";
const miniCls =
  "whitespace-nowrap font-mono text-[11px] tracking-[0.05em] text-(--t-3) max-md:w-full max-md:whitespace-normal";
const unmeasuredCls = "font-mono text-[11px] text-(--t-3)";
const emptyCls =
  "mt-3.5 flex flex-col items-center gap-3 rounded-[22px] border-0 bg-white px-6 py-[22px] text-center text-[13px] text-(--t-2)";
const btnCls =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-50";
const btnPrimaryCls =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black";

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

export default function ProjectSeoDetailPage() {
  const { t } = useTranslation();
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const numericProjectId = Number(projectId);
  const base = `/dashboard/projects/${projectId}`;
  const [activeTab, setActiveTab] = useState<TabId>("improve");
  const [open, setOpen] = useState<number | null>(null);
  // SIGV2-1145: "Add keyword" is a dialog on this tab. It used to navigate to
  // a monitoring page the approved MVP does not contain.
  const [addKeywordOpen, setAddKeywordOpen] = useState(false);

  // `?tab=` makes a single tab linkable from elsewhere in the product, which
  // is how the monitoring page's keyword list points back at the approved
  // place to add one (SIGV2-1145).
  const searchParams = useSearchParams();
  const requestedTab = searchParams?.get("tab") ?? null;
  useEffect(() => {
    if (requestedTab && (TABS as readonly string[]).includes(requestedTab)) {
      setActiveTab(requestedTab as TabId);
    }
  }, [requestedTab]);

  const { project, latestAudit, auditSelection, loading, error, refetch } = useProjectLatestAudit(
    projectId,
    { includeFullReport: true }
  );
  const { getToken, isSignedIn } = useAuth();

  // ------------------------------------------------------------------
  // Feeds: SERP keyword tracking, the tracked-keyword list and the Search
  // Console pages table (SIGV2-1025). Failure on any of them must not take
  // down the score page; each tab shows its own explicit unavailable state.
  // ------------------------------------------------------------------
  const [serp, setSerp] = useState<SerpTrackingSummary | null>(null);
  const [keywords, setKeywords] = useState<TargetKeyword[] | null>(null);
  const [keywordsFailed, setKeywordsFailed] = useState(false);
  const [gsc, setGsc] = useState<SearchConsolePagesResponse | null>(null);
  const [gscFailed, setGscFailed] = useState(false);

  const authHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  // A callback rather than an inline effect body, so adding a keyword can
  // reload the table it just filled (SIGV2-1145).
  const loadKeywords = useCallback(async () => {
    if (!projectId || !isSignedIn) return;
    try {
      const headers = await authHeaders();
      const [summary, list] = await Promise.all([
        fetchSerpTrackingSummary(projectId, headers),
        listTargetKeywords(projectId, headers),
      ]);
      setSerp(summary);
      setKeywords(list);
      setKeywordsFailed(false);
    } catch {
      setSerp(null);
      setKeywords(null);
      setKeywordsFailed(true);
    }
  }, [authHeaders, isSignedIn, projectId]);

  const loadPages = useCallback(async () => {
    if (!projectId || !isSignedIn) return;
    try {
      const headers = await authHeaders();
      setGsc(await fetchSearchConsolePages(projectId, headers));
      setGscFailed(false);
    } catch {
      setGsc(null);
      setGscFailed(true);
    }
  }, [authHeaders, isSignedIn, projectId]);

  useEffect(() => {
    void loadKeywords();
  }, [loadKeywords]);

  useEffect(() => {
    void loadPages();
  }, [loadPages]);

  const report = useMemo(() => {
    const raw = latestAudit?.full_report;
    return isAuditResult(raw) ? (raw as Record<string, any>) : null;
  }, [latestAudit?.full_report]);

  const seo = useMemo(
    () => (report?.seo && typeof report.seo === "object" ? report.seo : {}),
    [report]
  );

  const score = useMemo(() => {
    const canonical = roundOrNull(report?.scores?.seo ?? project?.latest_seo_score);
    if (canonical !== null) return canonical;
    const parts = [seo.onpage, seo.performance, seo.indexing].filter(
      (v): v is number => typeof v === "number" && Number.isFinite(v)
    );
    if (parts.length > 0) return Math.round(parts.reduce((a, b) => a + b, 0) / parts.length);
    return null;
  }, [report, seo, project?.latest_seo_score]);

  const heroEntranceRef = useSignalEntrance(
    `hero:${loading ? "loading" : "ready"}:${score ?? "-"}`
  );

  const factors = useMemo(() => {
    const build = (keys: readonly string[]) =>
      keys
        .map((key) => ({ key, score: roundOrNull((seo as any)[key]) }))
        .filter((f): f is { key: string; score: number } => f.score !== null);
    const measured = build(FACTOR_KEYS);
    return measured.length > 0 ? measured : build(LEGACY_FACTOR_KEYS);
  }, [seo]);

  // Recommendation titles are gated content: count them to decide whether the
  // improve panel exists, but only materialise the rows when the plan allows
  // the action plan (see the lockgate below).
  const improveCount = useMemo(() => {
    return deriveRecommendations(latestAudit).filter((r) => r.engines.includes("SEO")).length;
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
      .filter((r) => r.engines.includes("SEO"))
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

  // SIGV2-1036: the degraded-check banner, and why it is gated the way it is.
  //
  // This used to be a "Partial evidence" banner whose message was
  // `[degraded ? sentence : null, diagnostics.summary, serviceIssues[0]]`
  // joined. `diagnostics.summary` is never empty - it falls back to "Direct
  // audit evidence is available for the primary module cards and
  // recommendation context" - so the banner rendered on EVERY audit, and on a
  // healthy one it was an amber block titled "Partial evidence" whose own body
  // said the evidence was complete. Its 91px plus the 22px flow gap also
  // pushed the tab row and every section below it 109px (en) to 124px (ar)
  // down the page, misregistering the whole body against the approved frame.
  //
  // The self-contradiction was the defect, not the warning. A genuinely
  // degraded check is something the customer needs told, and this page is the
  // only drilldown that carries it: `AuditEvidenceStrip` exists but nothing
  // passes it `moduleDiagnostics`, and `RecommendationsHubClient`'s degraded
  // panel is not mounted anywhere. So the banner is back, gated on the audit
  // record's own status alone. No `diagnostics.summary` path: a message that
  // can never be empty is exactly what made the old block unconditional.
  //
  // The approved Signal SEO Detail.html has no element between the hero and
  // the tab row, so on a healthy check this page matches the approved frame
  // and nothing renders here. The stale-check banner above is the same kind of
  // real exception state and stays.
  const isDegradedAudit = latestAudit?.status === "degraded";

  const hasScore = score !== null;

  // ------------------------------------------------------------------
  // Keywords: keyword + position are real (tracked list joined to the latest
  // dated snapshot). Trend requires two dated snapshots per keyword; the
  // serp-tracking endpoint returns only the latest snapshot per keyword, so
  // the column is unmeasured with the reason attached, never derived from a
  // single point.
  // ------------------------------------------------------------------
  const keywordRows = useMemo(() => {
    const byKeywordId = new Map<number, SerpTrackingSummary["latest_snapshots"][number]>();
    for (const snap of serp?.latest_snapshots ?? []) byKeywordId.set(snap.keyword_id, snap);
    const rows: {
      id: number;
      keyword: string;
      position: number | null;
      snapshotDate: string | null;
    }[] = [];
    const seen = new Set<number>();
    for (const kw of keywords ?? []) {
      seen.add(kw.id);
      const snap = byKeywordId.get(kw.id);
      rows.push({
        id: kw.id,
        keyword: kw.keyword,
        position: snap?.organic_position ?? null,
        snapshotDate: snap?.snapshot_date ?? null,
      });
    }
    // Snapshots for keywords no longer active still carry real positions.
    for (const snap of serp?.latest_snapshots ?? []) {
      if (!seen.has(snap.keyword_id)) {
        rows.push({
          id: snap.keyword_id,
          keyword: snap.keyword,
          position: snap.organic_position ?? null,
          snapshotDate: snap.snapshot_date,
        });
      }
    }
    return rows;
  }, [serp, keywords]);

  // ------------------------------------------------------------------
  // Pages: the SIGV2-1025 contract. Sessions come from GA4, never from GSC
  // clicks; a missing sessions value renders its stated reason. Opportunity
  // is the backend verdict with its evidence; it is never recomputed here.
  // ------------------------------------------------------------------
  const gscPayload = isSearchConsolePagesPayload(gsc) ? gsc : null;
  const gscStub = gsc && !gscPayload ? (gsc as { status: string }) : null;

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
          { label: t("signalSeoDetail.crumbHome"), href: base },
          { label: t("signalSeoDetail.crumbCurrent") },
        ]}
      />
    ),
    [t, base]
  );
  const topActions = useMemo(
    () => (
      <>
        <SignalExportMenu
          page="seo"
          reportKind="seo"
          auditId={auditId}
          projectId={Number.isFinite(numericProjectId) ? numericProjectId : null}
        />
        <Link href={`${base}/settings`} className={btnPrimaryCls}>
          {t("signalSeoDetail.improveSettings")}
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
      <div role="status" aria-label={t("signalGoogle.loading")} className="flex flex-col gap-5">
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

  const tabCounts: Record<TabId, number> = {
    improve: improveCount,
    factors: factors.length,
    keywords: keywordRows.length,
    pages: gscPayload?.pages?.length ?? 0,
  };
  const tabLabels: Record<TabId, string> = {
    improve: t("signalSeoDetail.tabImprove"),
    factors: t("signalSeoDetail.tabFactors"),
    keywords: t("signalSeoDetail.tabKeywords"),
    pages: t("signalSeoDetail.tabPages"),
  };

  return (
    // SIGV2-1036: the approved page's own <style> overrides the shared
    // `.wrap{padding:20px 32px 14px}` to `26px 32px 52px`, and the dashboard
    // shell supplies the shared value, so the built body sits 4px above the
    // approved frame in English. Adding the 6px/38px difference here was
    // measured and reverted: the extra 38px at the bottom pushes a panel past
    // the shell's min-height and grows the document beyond the approved page
    // (aio-detail-tab-types ar went 915px -> 930px and 16.85% -> 20.78%,
    // over budget), and the 6px at the top only helps English. The Arabic
    // hero is 165px in the approved page against 182-196px here, because the
    // Arabic strings are longer, so the Arabic body already sits ~11px BELOW
    // the frame and 6px more makes it worse. Closing this needs the Arabic
    // hero height resolved first, not padding.
    <div className="flex min-w-0 flex-col gap-4">
      <div ref={heroEntranceRef} className="flex flex-col gap-3.5">
        <SignalScoreHero
          score={score}
          eyebrow={t("signalSeoDetail.eyebrow")}
          title={t("signalSeoDetail.heroTitle")}
          copy={
            <>
              {t("signalSeoDetail.heroCopy")}{" "}
              {hasScore
                ? t("signalSeoDetail.heroCopyScored")
                : t("signalSeoDetail.heroCopyNoScore")}
            </>
          }
          currentScoreLabel={t("signalSeoDetail.currentScore")}
          emptyLabel={
            <span className="font-(family-name:--body-font) text-[11px] font-semibold tracking-normal text-(--t-3)">
              {t("signalOverview.notMeasured")}
            </span>
          }
          targetLine={
            project?.score_targets?.seo == null
              ? t("signalSeoDetail.noTargets")
              : project.score_targets.seo.gap === null
                ? t("signalSeoDetail.targetUnmeasured", {
                    target: project.score_targets.seo.target,
                  })
                : project.score_targets.seo.gap === 0
                  ? t("signalSeoDetail.atTarget", {
                      target: project.score_targets.seo.target,
                    })
                  : t("signalSeoDetail.targetLine", {
                      target: project.score_targets.seo.target,
                      gap: Math.round(project.score_targets.seo.gap),
                    })
          }
        />

        {auditSelection?.status === "stale" && (
          <ProjectFeatureBanner
            title={t("signalGoogle.stale.title")}
            message={auditSelection.message}
          />
        )}
        {isDegradedAudit && (
          <ProjectFeatureBanner
            title={t("signalGoogle.degraded.title")}
            tone="amber"
            message={t("signalGoogle.degraded.message")}
          />
        )}

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
            title={t("signalSeoDetail.improveTitle")}
            mini={
              advisorPlan.allowed
                ? t("signalSeoDetail.improveMini", {
                    shown: improve.length,
                    total: improveCount,
                  })
                : t("signalSeoDetail.improveMiniLocked", { total: improveCount })
            }
            action={
              <Link
                href={`${base}/fixes`}
                className="inline-flex h-[30px] cursor-pointer items-center gap-2 rounded-lg border-0 bg-white px-[11px] font-(family-name:--body-font) text-[12px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
              >
                {t("signalSeoDetail.advisorActionPlan")}
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
                <div className="rounded-[22px] border-0 bg-white">
                  {!advisorPlan.allowed ? (
                    // Blur is presentation, not authorization: gated rows
                    // must not sit in the DOM, so render the approved .act
                    // anatomy with generic illustrative copy, never the
                    // customer's recommendations.
                    <LockedActPreview accent="blue" />
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
                            <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
                              {a.category}
                            </span>
                            {/* SIGV2-1193: one consolidated list, so each row
                                says which channel raised it rather than the
                                list as a whole naming one source. */}
                            {fixSourceLabelKeys(a.sources).map((key) => (
                              <span
                                key={key}
                                className="rounded-[6px] border-0 bg-[#EEF1F6] px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--t-3)"
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
                  ? t("signalSeoDetail.improveEmpty")
                  : t("signalSeoDetail.improveEmptyNoScore")}
              </span>
            </div>
          )}
        </div>

        {/* RANKING FACTORS */}
        <div
          role="tabpanel"
          id="signal-tabpanel-factors"
          aria-labelledby="signal-tab-factors"
          hidden={activeTab !== "factors"}
        >
          <Sec title={t("signalSeoDetail.factorsTitle")} mini={t("signalSeoDetail.factorsMini")} />
          {factors.length > 0 ? (
            <div className="rounded-[22px] border-0 bg-white">
              {factors.map((f, i) => (
                <div className="border-t border-t-(--line-2) first:border-t-0" key={f.key}>
                  <button
                    type="button"
                    className="flex w-full cursor-pointer items-center gap-3.5 border-current px-[22px] py-4 text-left font-normal hover:bg-(--line-2) focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--blue)"
                    aria-expanded={open === i}
                    onClick={() => setOpen(open === i ? null : i)}
                  >
                    <span
                      className="w-[52px] flex-none font-(family-name:--disp) text-[26px] font-black tracking-[-0.02em] text-(--sc)"
                      style={{ "--sc": scoreColor(f.score) } as React.CSSProperties}
                    >
                      {f.score}
                    </span>
                    <span className="flex-1">
                      <span className="block font-(family-name:--disp) text-[14.5px] font-bold">
                        {t(`signalGoogle.factors.items.${f.key}.label`)}
                      </span>
                    </span>
                    <span className="block h-[7px] w-[150px] flex-none overflow-hidden rounded-[999px] bg-(--line)">
                      <i
                        className="block h-full w-(--sw) origin-left rounded-[999px] bg-(--sc) rtl:origin-right"
                        data-signal-enter="bar"
                        style={
                          {
                            "--sw": `${f.score}%`,
                            "--sc": scoreColor(f.score),
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
                      {t("signalGoogle.factors.measured")}
                    </div>
                    <p className="m-0 text-[13px] leading-[1.55] text-(--t-2)">
                      {t(`signalGoogle.factors.items.${f.key}.desc`)}.{" "}
                      {t("signalGoogle.factors.scoredIn", { score: f.score })}
                    </p>
                    {/* Per-factor fix lists have no source: recommendations are
                        emitted globally, not keyed to a factor, and the
                        category-to-factor mapping would be a guess. The slot
                        names that rather than re-showing the global list
                        under a factor heading. */}
                    <div className="mt-4 mb-1.5 text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      {t("signalSeoDetail.howImprove")}
                    </div>
                    <p className={unmeasuredCls}>{t("signalSeoDetail.factorActionsUnmeasured")}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className={emptyCls}>
              <span>{t("signalGoogle.factors.empty")}</span>
            </div>
          )}
        </div>

        {/* KEYWORDS */}
        <div
          role="tabpanel"
          id="signal-tabpanel-keywords"
          aria-labelledby="signal-tab-keywords"
          hidden={activeTab !== "keywords"}
        >
          <Sec
            title={t("signalSeoDetail.keywordsTitle")}
            action={
              <button
                type="button"
                className={`${btnCls} h-[32px]`}
                onClick={() => setAddKeywordOpen(true)}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  className="h-[15px] w-[15px]"
                  strokeWidth={2}
                  strokeLinecap="round"
                >
                  <path d="M12 5v14M5 12h14" />
                </svg>
                {t("signalSeoDetail.addKeyword")}
              </button>
            }
          />
          {keywordsFailed ? (
            <div className={emptyCls}>
              <span>{t("signalSeoDetail.keywordsFailed")}</span>
            </div>
          ) : keywordRows.length > 0 ? (
            <div className="overflow-x-auto rounded-[22px] border-0 bg-white">
              <table className="min-w-full">
                <thead>
                  <tr>
                    {(["colKeyword", "colPosition", "colTrend"] as const).map((key) => (
                      <th
                        key={key}
                        className="border-b border-b-(--line) px-[22px] py-3 text-start font-mono text-[10.5px] uppercase tracking-[0.06em] text-(--t-3)"
                      >
                        {t(`signalSeoDetail.${key}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {keywordRows.map((row) => (
                    <tr key={row.id} className="border-b border-b-(--line-2) last:border-b-0">
                      <td className="px-[22px] py-[13px] text-[13.5px] font-medium text-(--t-1)">
                        {row.keyword}
                      </td>
                      <td className="px-[22px] py-[13px] text-[13.5px] text-(--t-1)">
                        {row.position !== null ? (
                          `#${row.position}`
                        ) : (
                          <span
                            className={unmeasuredCls}
                            title={
                              row.snapshotDate
                                ? t("signalSeoDetail.positionPendingReason")
                                : t("signalSeoDetail.positionNoSnapshotReason")
                            }
                          >
                            {t("signalOverview.notMeasured")}
                          </span>
                        )}
                      </td>
                      {/* Trend needs two dated snapshots per keyword; the
                          endpoint returns the latest snapshot only, so this
                          is never derived from a single point. */}
                      <td
                        data-col="trend"
                        className="px-[22px] py-[13px]"
                        title={t("signalSeoDetail.trendReason")}
                      >
                        <span className={unmeasuredCls}>{t("signalOverview.notMeasured")}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={emptyCls}>
              <span>{t("signalSeoDetail.keywordsEmpty")}</span>
              <button
                type="button"
                className={btnPrimaryCls}
                onClick={() => setAddKeywordOpen(true)}
              >
                {t("signalSeoDetail.keywordsEmptyCta")}
              </button>
            </div>
          )}
        </div>

        {/* PAGES */}
        <div
          role="tabpanel"
          id="signal-tabpanel-pages"
          aria-labelledby="signal-tab-pages"
          hidden={activeTab !== "pages"}
        >
          <Sec
            title={t("signalSeoDetail.pagesTitle")}
            mini={
              gscPayload
                ? t("signalSeoDetail.pagesMini", {
                    window: gscPayload.window,
                    basis: gscPayload.date_basis,
                  })
                : undefined
            }
          />
          {gscFailed ? (
            <div className={emptyCls}>
              <span>{t("signalSeoDetail.pagesFailed")}</span>
            </div>
          ) : gscStub ? (
            <div className={emptyCls}>
              <span>
                {gscStub.status === "disconnected"
                  ? t("signalSeoDetail.pagesDisconnected")
                  : gscStub.status === "revoked"
                    ? t("signalSeoDetail.pagesRevoked")
                    : t("signalSeoDetail.pagesFailed")}
              </span>
              {gscStub.status === "disconnected" || gscStub.status === "revoked" ? (
                <Link href={`${base}/settings`} className={btnPrimaryCls}>
                  {t("signalSeoDetail.pagesConnectCta")}
                </Link>
              ) : null}
            </div>
          ) : gscPayload ? (
            <>
              {gscPayload.date_alignment === "approximate" ? (
                <p className="m-0 mb-3 text-[12px] text-(--t-3)">
                  {t("signalSeoDetail.pagesApproximate", {
                    basis: gscPayload.date_basis,
                    tz: gscPayload.ga4_property_timezone ?? t("signalSeoDetail.pagesNoGa4Tz"),
                  })}
                </p>
              ) : null}
              {gscPayload.completeness !== "full" && gscPayload.partial_reason ? (
                <p className="m-0 mb-3 text-[12px] text-(--warn)">{gscPayload.partial_reason}</p>
              ) : null}
              <div className="overflow-x-auto rounded-[22px] border-0 bg-white">
                <table className="min-w-full">
                  <thead>
                    <tr>
                      {(
                        ["colPage", "colSessions", "colAvgPosition", "colOpportunity"] as const
                      ).map((key) => (
                        <th
                          key={key}
                          className="border-b border-b-(--line) px-[22px] py-3 text-start font-mono text-[10.5px] uppercase tracking-[0.06em] text-(--t-3)"
                        >
                          {t(`signalSeoDetail.${key}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {gscPayload.pages.map((page: SearchConsolePageRow) => (
                      <tr
                        key={page.page_key}
                        className="border-b border-b-(--line-2) last:border-b-0"
                      >
                        <td className="px-[22px] py-[13px] text-[13.5px] font-medium text-(--t-1)">
                          <span className="inline-flex items-center gap-2">
                            {page.page_key}
                            {page.incomplete ? (
                              <span
                                className="rounded-[6px] bg-(--line-2) px-1.5 py-px font-mono text-[10px] text-(--t-3)"
                                title={t("signalSeoDetail.incompleteReason")}
                              >
                                {t("signalSeoDetail.incompleteBadge")}
                              </span>
                            ) : null}
                          </span>
                        </td>
                        {/* Sessions are GA4 values, never GSC clicks. A
                            missing value renders its stated reason, not a
                            blank and not the click count. */}
                        <td className="px-[22px] py-[13px] text-[13.5px] text-(--t-1)">
                          {page.sessions !== null ? (
                            formatNumber(page.sessions)
                          ) : (
                            <span
                              className={unmeasuredCls}
                              data-reason={page.sessions_reason ?? "unknown"}
                              title={t(
                                `signalSeoDetail.sessionsReason.${page.sessions_reason ?? "unknown"}`
                              )}
                            >
                              {t("signalSeoDetail.sessionsUnavailable")}
                            </span>
                          )}
                        </td>
                        <td className="px-[22px] py-[13px] text-[13.5px] text-(--t-1)">
                          {formatPosition(page.avg_position)}
                        </td>
                        {/* The verdict is the backend's classification with
                            its own evidence; it is rendered, not recomputed. */}
                        <td
                          className="px-[22px] py-[13px] text-[13.5px] text-(--t-1)"
                          title={t("signalSeoDetail.opportunityEvidence", {
                            position: formatPosition(page.opportunity.evidence.weighted_position),
                            impressions: formatNumber(page.opportunity.evidence.impressions),
                            ctr:
                              page.opportunity.evidence.ctr !== null
                                ? `${(page.opportunity.evidence.ctr * 100).toFixed(1)}%`
                                : "-",
                            median:
                              page.opportunity.evidence.band_median_ctr !== null
                                ? `${(page.opportunity.evidence.band_median_ctr * 100).toFixed(1)}%`
                                : "-",
                          })}
                        >
                          {t(`signalSeoDetail.opportunity.${page.opportunity.value}`)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className={emptyCls}>
              <span>{t("signalSeoDetail.pagesEmpty")}</span>
            </div>
          )}
        </div>
      </div>

      <SignalAddKeywordModal
        open={addKeywordOpen}
        onClose={() => setAddKeywordOpen(false)}
        projectId={projectId}
        getAuthHeaders={authHeaders}
        onCreated={loadKeywords}
      />
    </div>
  );
}
