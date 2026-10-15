"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Globe, Layers, RefreshCw, ScanSearch, ShieldAlert, Sparkles } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import {
  ProjectFeatureEmptyState,
  ProjectFeatureErrorState,
  ProjectFeatureHeader,
  ProjectFeatureLoadingView,
} from "@/components/dashboard/ProjectFeatureScaffold";
import Button from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";
import PageLoaderOverlay from "@/components/ui/PageLoaderOverlay";
import Badge from "@/components/ui/Badge";
import CrawlModeComparisonCard, {
  deriveCrawlRecommendation,
} from "@/components/dashboard/CrawlModeComparisonCard";
import SmartCrawlExplanation from "@/components/dashboard/SmartCrawlExplanation";
import {
  estimateProjectSitemapCrawl,
  estimateSmartCrawl,
  fetchLatestProjectSitemapCrawl,
  fetchSitemapCrawlReport,
  fetchSitemapCrawlStatus,
  startProjectSitemapCrawl,
  startSmartCrawl,
  type SitemapCrawlEstimate,
  type SitemapCrawlReport,
  type SitemapCrawlStatus,
  type SmartCrawlEstimate,
} from "@/services/workspaceService";

type CrawlMode = "bulk" | "smart";

export default function ProjectSiteCrawlPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();

  const [mode, setMode] = useState<CrawlMode>("smart");
  const [sitemapUrl, setSitemapUrl] = useState("");
  const [estimate, setEstimate] = useState<SitemapCrawlEstimate | null>(null);
  const [smartEstimate, setSmartEstimate] = useState<SmartCrawlEstimate | null>(null);
  const [crawlStatus, setCrawlStatus] = useState<SitemapCrawlStatus | null>(null);
  const [crawlReport, setCrawlReport] = useState<SitemapCrawlReport | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [startLoading, setStartLoading] = useState(false);
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) throw new Error("Sign in to manage sitemap crawls.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadStatus = useCallback(
    async (jobId: string, includeReport: boolean) => {
      const headers = await getAuthHeaders();
      const statusPayload = await fetchSitemapCrawlStatus(jobId, headers);
      setCrawlStatus(statusPayload);

      if (statusPayload.status === "completed" || includeReport) {
        const reportPayload = await fetchSitemapCrawlReport(jobId, headers);
        setCrawlReport(reportPayload);
      }
    },
    [getAuthHeaders]
  );

  // Recover an in-progress or completed crawl on mount, so navigating away and
  // back (or a plain refresh) doesn't lose progress or force a re-run.
  useEffect(() => {
    if (!projectId || !isSignedIn || activeJobId) return;

    let cancelled = false;

    void (async () => {
      try {
        const headers = await getAuthHeaders();
        const latestJob = await fetchLatestProjectSitemapCrawl(projectId, headers);
        if (cancelled || !latestJob) return;

        setActiveJobId(latestJob.id);
        setSitemapUrl((current) => current || latestJob.sitemap_url);
        setCrawlStatus(latestJob);

        if (latestJob.status === "completed") {
          const reportPayload = await fetchSitemapCrawlReport(latestJob.id, headers);
          if (!cancelled) setCrawlReport(reportPayload);
        }
      } catch {
        // No recoverable crawl (or the lookup failed); stay in the empty state.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [projectId, isSignedIn, activeJobId, getAuthHeaders]);

  useEffect(() => {
    if (!activeJobId) return;

    const currentStatus = crawlStatus?.status;
    if (!currentStatus || ["parsing", "queuing", "running"].includes(currentStatus)) {
      const intervalId = window.setInterval(() => {
        void loadStatus(activeJobId, false).catch(() => {
          // Silent polling retry; explicit errors surface on manual actions.
        });
      }, 3000);
      return () => window.clearInterval(intervalId);
    }

    return undefined;
  }, [activeJobId, crawlStatus?.status, loadStatus]);

  const estimateCost = async () => {
    if (!projectId) return;
    setEstimateLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      if (mode === "smart") {
        const payload = await estimateSmartCrawl(projectId, { sitemap_url: sitemapUrl }, headers);
        setSmartEstimate(payload);
        setEstimate(null);
      } else {
        const payload = await estimateProjectSitemapCrawl(
          projectId,
          { sitemap_url: sitemapUrl },
          headers
        );
        setEstimate(payload);
        setSmartEstimate(null);
      }
    } catch (estimateError) {
      setEstimate(null);
      setSmartEstimate(null);
      setError(
        estimateError instanceof Error ? estimateError.message : "Unable to estimate crawl cost."
      );
    } finally {
      setEstimateLoading(false);
    }
  };

  const startCrawl = async () => {
    if (!projectId) return;
    setStartLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const payload =
        mode === "smart"
          ? await startSmartCrawl(projectId, { sitemap_url: sitemapUrl }, headers)
          : await startProjectSitemapCrawl(projectId, { sitemap_url: sitemapUrl }, headers);
      setActiveJobId(payload.job_id);
      setCrawlStatus({
        id: payload.job_id,
        project_id: Number(projectId),
        user_id: 0,
        sitemap_url: sitemapUrl,
        status: payload.status,
        total_urls: payload.total_urls,
        completed_urls: 0,
        failed_urls: 0,
        error: null,
        created_at: null,
        completed_at: null,
      });
      setCrawlReport(null);
      await loadStatus(payload.job_id, false);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "Unable to start crawl.");
    } finally {
      setStartLoading(false);
    }
  };

  const refreshStatus = async () => {
    if (!activeJobId) return;
    setRefreshLoading(true);
    setError(null);
    try {
      await loadStatus(activeJobId, true);
    } catch (statusError) {
      setError(
        statusError instanceof Error ? statusError.message : "Unable to refresh crawl status."
      );
    } finally {
      setRefreshLoading(false);
    }
  };

  const progress = useMemo(() => {
    if (!crawlStatus?.total_urls || crawlStatus.total_urls <= 0) return 0;
    const done = crawlStatus.completed_urls + crawlStatus.failed_urls;
    return Math.min(100, Math.round((done / crawlStatus.total_urls) * 100));
  }, [crawlStatus]);

  /* Crawl-mode recommendation based on estimate data */
  const crawlRecommendation = useMemo(() => {
    const siteUrls = smartEstimate?.total_site_urls ?? estimate?.url_count ?? null;
    const hasExistingCrawl = crawlReport !== null;
    return deriveCrawlRecommendation(siteUrls, hasExistingCrawl);
  }, [smartEstimate, estimate, crawlReport]);

  const backgroundLoading = estimateLoading || startLoading || refreshLoading;
  const overlayLabel = startLoading
    ? `Starting ${mode === "smart" ? "smart" : "sitemap"} crawl...`
    : refreshLoading
      ? "Refreshing crawl status..."
      : "Estimating crawl cost...";
  const overlayDetail = startLoading
    ? "Queuing the sitemap audit job and preparing the first progress snapshot."
    : refreshLoading
      ? "Pulling the latest sitemap crawl status and aggregated report data."
      : "Calculating the projected crawl size before launch.";

  if (authLoading) {
    return (
      <section className="space-y-8 pb-12">
        <ProjectFeatureLoadingView
          label="Preparing sitemap crawler..."
          icon={ScanSearch}
          title="Site"
          accent="Crawl"
          description="Preparing the crawl workspace, sitemap controls, and aggregated reporting surface."
          metrics={4}
          panels={2}
        />
      </section>
    );
  }

  if (!isSignedIn) {
    return (
      <section className="space-y-8 pb-12">
        <ProjectFeatureHeader
          icon={ScanSearch}
          title="Site"
          accent="Crawl"
          description="Audit your site pages, choose smart sampling for efficient coverage or bulk crawl for exhaustive analysis."
        />
        <ProjectFeatureEmptyState
          icon={ShieldAlert}
          title="Sign in to run sitemap crawls"
          description="This project workflow needs an authenticated workspace session before you can estimate crawls, launch crawls, or review the aggregated report."
        />
      </section>
    );
  }

  return (
    <section className="space-y-8 pb-12">
      <ProjectFeatureHeader
        icon={ScanSearch}
        title="Site"
        accent="Crawl"
        description="Audit your site pages, choose smart sampling for efficient coverage or bulk crawl for exhaustive analysis."
      />

      {error ? <ProjectFeatureErrorState title="Crawl error" message={error} /> : null}

      <PageLoaderOverlay loading={backgroundLoading} label={overlayLabel} detail={overlayDetail}>
        <div className="space-y-6">
          {/* ── Mode Toggle ── */}
          <div className="flex items-center gap-2">
            <ModeTab
              active={mode === "smart"}
              icon={<Sparkles className="h-4 w-4" />}
              label="Smart Crawl"
              onClick={() => setMode("smart")}
            />
            <ModeTab
              active={mode === "bulk"}
              icon={<Layers className="h-4 w-4" />}
              label="Bulk Crawl"
              onClick={() => setMode("bulk")}
            />
          </div>

          {/* ── Comparison Card ── */}
          <CrawlModeComparisonCard
            recommendation={smartEstimate || estimate ? crawlRecommendation : null}
            activeMode={mode}
            onSelectMode={setMode}
          />

          {/* ── Crawl Setup ── */}
          <GlassCard className="space-y-4 border-(--line) bg-[color-mix(in_srgb,var(--panel)_70%,transparent)] p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.24em] text-primary">
                  {mode === "smart" ? "Smart Crawl" : "Bulk Crawl"}
                </p>
                <h2 className="mt-2 text-xl font-black tracking-tight text-(--t-1)">
                  {mode === "smart"
                    ? "Sample representative pages by type"
                    : "Launch a bulk sitemap run"}
                </h2>
                {mode === "smart" ? (
                  <p className="mt-1 text-sm text-(--t-2)">
                    Intelligently selects a few pages per page type (homepage, product, blog, etc.)
                    to give you site-wide insights at a fraction of the cost.
                  </p>
                ) : null}
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border-0 bg-primary/10 text-primary">
                {mode === "smart" ? (
                  <Sparkles className="h-5 w-5" />
                ) : (
                  <Globe className="h-5 w-5" />
                )}
              </div>
            </div>

            <label
              className="block text-xs font-bold uppercase tracking-wider text-(--t-2)"
              htmlFor="sitemap-url"
            >
              Sitemap URL
            </label>
            <input
              id="sitemap-url"
              type="url"
              value={sitemapUrl}
              onChange={(event) => setSitemapUrl(event.target.value)}
              placeholder="https://example.com/sitemap.xml"
              className="w-full rounded-xl border-0 bg-white px-4 py-2.5 text-sm text-(--t-1) outline-hidden transition focus:border-primary/60"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="ghost"
                onClick={() => void estimateCost()}
                loading={estimateLoading}
                loadingText="Estimating..."
              >
                Estimate Cost
              </Button>
              <Button
                onClick={() => void startCrawl()}
                loading={startLoading}
                loadingText="Starting..."
              >
                {mode === "smart" ? "Start Smart Crawl" : "Start Crawl"}
              </Button>
              {activeJobId ? (
                <Button
                  variant="ghost"
                  onClick={() => void refreshStatus()}
                  loading={refreshLoading}
                  loadingText="Refreshing..."
                >
                  <RefreshCw className="h-4 w-4" />
                  Refresh Status
                </Button>
              ) : null}
            </div>

            {/* Bulk estimate */}
            {estimate ? (
              <div className="rounded-xl border-0 bg-[color-mix(in_srgb,var(--panel)_70%,transparent)] p-3 text-sm text-(--t-1)">
                Estimated crawl size: <strong>{estimate.url_count}</strong> pages
              </div>
            ) : null}

            {/* Smart estimate with page-type breakdown */}
            {smartEstimate ? <SmartEstimatePanel estimate={smartEstimate} /> : null}
          </GlassCard>

          {/* ── Progress ── */}
          {crawlStatus ? (
            <GlassCard className="space-y-3 border-(--line) bg-[color-mix(in_srgb,var(--panel)_70%,transparent)] p-5">
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <p className="font-semibold text-(--t-1)">
                  Status: <span className="capitalize">{crawlStatus.status.replace("_", " ")}</span>
                </p>
                <p className="text-(--t-2)">
                  {crawlStatus.completed_urls + crawlStatus.failed_urls} /{" "}
                  {crawlStatus.total_urls ?? "--"} pages audited
                </p>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-(--line-2)">
                <div
                  className="h-2 w-(--pw) rounded-full bg-linear-to-r from-thoth-brass to-thoth-logic transition-all"
                  style={{ "--pw": `${progress}%` } as React.CSSProperties}
                  aria-hidden="true"
                />
              </div>
              <div className="grid gap-2 text-xs text-(--t-2) md:grid-cols-3">
                <p>Completed: {crawlStatus.completed_urls}</p>
                <p>Failed: {crawlStatus.failed_urls}</p>
              </div>
              {crawlStatus.error ? (
                <p className="text-sm text-rose-300">{crawlStatus.error}</p>
              ) : null}
            </GlassCard>
          ) : null}

          {/* ── Report ── */}
          {crawlReport?.report ? (
            <>
              {/* Smart Crawl analysis (when available) */}
              {crawlReport.report.smart_crawl ? (
                <SmartCrawlExplanation
                  smartCrawl={crawlReport.report.smart_crawl}
                  pageTypeBreakdown={crawlReport.report.page_type_breakdown}
                />
              ) : null}

              <GlassCard className="space-y-4 border-(--line) bg-[color-mix(in_srgb,var(--panel)_70%,transparent)] p-5">
                <h2 className="text-xl font-black text-(--t-1)">Site Health Report</h2>
                <div className="grid gap-3 md:grid-cols-4">
                  <MetricCard
                    label="Site Health"
                    value={crawlReport.report.aggregated_scores?.site_health}
                  />
                  <MetricCard
                    label="AI visibility"
                    value={crawlReport.report.aggregated_scores?.geo}
                  />
                  <MetricCard label="SEO" value={crawlReport.report.aggregated_scores?.seo} />
                  <MetricCard
                    label="AI answers"
                    value={crawlReport.report.aggregated_scores?.aeo}
                  />
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-xl border-0 bg-[color-mix(in_srgb,var(--panel)_80%,transparent)] p-4">
                    <p className="text-xs font-bold uppercase tracking-wider text-(--t-2)">
                      Score Distribution
                    </p>
                    <ul className="mt-3 space-y-2 text-sm text-(--t-1)">
                      <li>80+: {crawlReport.report.score_distribution?.["80_plus"] ?? 0}</li>
                      <li>60-79: {crawlReport.report.score_distribution?.["60_79"] ?? 0}</li>
                      <li>40-59: {crawlReport.report.score_distribution?.["40_59"] ?? 0}</li>
                      <li>&lt; 40: {crawlReport.report.score_distribution?.below_40 ?? 0}</li>
                    </ul>
                  </div>
                  <div className="rounded-xl border-0 bg-[color-mix(in_srgb,var(--panel)_80%,transparent)] p-4">
                    <p className="text-xs font-bold uppercase tracking-wider text-(--t-2)">
                      Top Issue Categories
                    </p>
                    <ul className="mt-3 space-y-2 text-sm text-(--t-1)">
                      {(crawlReport.report.top_issues ?? []).length === 0 ? (
                        <li className="text-(--t-2)">
                          No recommendation categories available yet.
                        </li>
                      ) : (
                        (crawlReport.report.top_issues ?? []).map((issue) => (
                          <li key={issue.category}>
                            {issue.category} <span className="text-(--t-2)">({issue.count})</span>
                          </li>
                        ))
                      )}
                    </ul>
                  </div>
                </div>

                <div className="rounded-xl border-0 bg-[color-mix(in_srgb,var(--panel)_80%,transparent)] p-4">
                  <p className="text-xs font-bold uppercase tracking-wider text-(--t-2)">
                    Worst-performing Pages
                  </p>
                  <div className="mt-3 overflow-x-auto">
                    <table className="min-w-full text-sm border-collapse">
                      <thead>
                        <tr className="border-b border-(--line) text-left text-xs uppercase tracking-wider text-(--t-2)">
                          <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                            URL
                          </th>
                          <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                            Type
                          </th>
                          <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                            Overall
                          </th>
                          <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                            AI visibility
                          </th>
                          <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                            SEO
                          </th>
                          <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                            AI answers
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(crawlReport.report.worst_pages ?? []).map((page) => (
                          <tr
                            key={page.url}
                            className="border-b border-(--line) text-(--t-1) last:[&>td]:border-b-0"
                          >
                            <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                              {page.url}
                            </td>
                            <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2) capitalize text-(--t-2)">
                              {page.page_type?.replace(/_/g, " ") ?? "\u2014"}
                            </td>
                            <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                              {page.overall ?? "--"}
                            </td>
                            <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                              {page.geo ?? "--"}
                            </td>
                            <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                              {page.seo ?? "--"}
                            </td>
                            <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                              {page.aeo ?? "--"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </GlassCard>
            </>
          ) : null}
        </div>
      </PageLoaderOverlay>
    </section>
  );
}

/* ── Sub-components ── */

function ModeTab({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition ${active ? "border-0 bg-[#E8F1FF] text-[#1D4ED8]" : "border-0 bg-[color-mix(in_srgb,var(--panel)_60%,transparent)] text-(--t-2) hover:border-(--line) hover:text-(--t-1)"}`}
    >
      {icon}
      {label}
    </button>
  );
}

function SmartEstimatePanel({ estimate }: { estimate: SmartCrawlEstimate }) {
  const activePlan = estimate.plan.filter((p) => !p.skipped);
  const skippedPlan = estimate.plan.filter((p) => p.skipped);

  return (
    <div className="space-y-3 rounded-xl border-0 bg-[color-mix(in_srgb,var(--panel)_70%,transparent)] p-4">
      <div className="flex flex-wrap items-center gap-4 text-sm text-(--t-1)">
        <span>
          Site pages: <strong>{estimate.total_site_urls}</strong>
        </span>
        <span>
          Page types: <strong>{estimate.total_page_types}</strong>
        </span>
        <span>
          Sampled: <strong>{estimate.sampled_urls_count}</strong> pages
        </span>
      </div>

      {activePlan.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-bold uppercase tracking-wider text-(--t-2)">
            Sampling Plan
          </p>
          <div className="space-y-1.5">
            {activePlan.map((item) => (
              <div
                key={item.page_type}
                className="flex items-center justify-between gap-2 rounded border-0 bg-[color-mix(in_srgb,var(--panel)_40%,transparent)] px-3 py-1.5 text-sm"
              >
                <span className="font-medium text-(--t-1)">{item.label}</span>
                <span className="text-(--t-2)">
                  {item.sampled_urls} / {item.total_urls} pages
                  <span className="ml-2 text-xs text-(--t-3)">
                    ({Math.round(item.coverage_ratio * 100)}%)
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {skippedPlan.length > 0 ? (
        <div>
          <p className="mb-1 text-xs font-bold uppercase tracking-wider text-(--t-3)">
            Skipped (low-value)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {skippedPlan.map((item) => (
              <Badge key={item.page_type} color="default" size="sm">
                {item.label} ({item.total_urls})
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="rounded-xl border-0 bg-[color-mix(in_srgb,var(--panel)_80%,transparent)] p-4">
      <p className="text-xs font-bold uppercase tracking-wider text-(--t-2)">{label}</p>
      <p className="mt-2 text-2xl font-black text-(--t-1)">
        {typeof value === "number" ? Math.round(value) : "--"}
      </p>
    </div>
  );
}
