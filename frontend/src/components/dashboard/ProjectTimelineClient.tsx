"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  GitCommitHorizontal,
  Loader2,
  Minus,
  Search,
  Sparkles,
} from "lucide-react";
import { motion } from "motion/react";
import { useAuth } from "@/components/auth/custom-auth";
import { GlassCard } from "@/components/ui/GlassComponents";
import GeoIcon from "@/components/ui/GeoIcon";
import Button from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";
import { formatDateTime } from "@/lib/dateFormat";
import ProjectTrendChart from "@/components/dashboard/ProjectTrendChart";
import {
  fetchProjectAudits,
  fetchProjectById,
  fetchProjectTrendComparison,
  fetchProjectTrends,
  type ProjectAuditHistoryEntry,
  type ProjectTrendComparisonResponse,
  type ProjectTrendResponse,
} from "@/services/workspaceService";

const PERIOD_OPTIONS = [
  { label: "30D", value: "30d" as const },
  { label: "90D", value: "90d" as const },
  { label: "1Y", value: "1y" as const },
  { label: "All", value: "all" as const },
];

const GRANULARITY_OPTIONS = [
  { label: "Daily", value: "daily" as const },
  { label: "Weekly", value: "weekly" as const },
  { label: "Monthly", value: "monthly" as const },
];

const normalizeProjectUrl = (value: string | null | undefined): string => {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) {
    return "";
  }
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }
  return `https://${trimmed}`;
};

const resolveComparisonPeriod = (period: "30d" | "90d" | "1y" | "all"): "30d" | "90d" | "1y" => {
  if (period === "all") {
    return "90d";
  }
  return period;
};

function ScoreMovementCard({ label, value }: { label: string; value: number | null }) {
  const rounded = typeof value === "number" ? Math.round(value * 10) / 10 : null;

  const colors =
    rounded === null
      ? "border-(--line) bg-(--line-2) text-(--t-2)"
      : rounded > 0
        ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
        : rounded < 0
          ? "border-rose-500/20 bg-rose-500/10 text-rose-300"
          : "border-(--line) bg-(--line-2) text-(--t-2)";

  return (
    <div className={cx("rounded border p-5", colors)}>
      <p className="text-[10px] font-black uppercase tracking-[0.24em]">{label}</p>
      <div className="mt-4 flex items-center gap-2">
        {rounded === null ? (
          <Minus className="h-4 w-4" />
        ) : rounded > 0 ? (
          <ArrowUpRight className="h-4 w-4" />
        ) : rounded < 0 ? (
          <ArrowDownRight className="h-4 w-4" />
        ) : (
          <Minus className="h-4 w-4" />
        )}
        <p className="text-2xl font-black text-(--t-1)">
          {rounded === null ? "--" : `${rounded > 0 ? "+" : ""}${rounded}`}
        </p>
      </div>
    </div>
  );
}

function AuditScoreBadge({
  label,
  icon,
  current,
  previous,
}: {
  label: string;
  icon: React.ReactNode;
  current: number | null;
  previous: number | null;
}) {
  if (current === null) {
    return null;
  }

  const delta = previous !== null ? current - previous : 0;
  const colorClass =
    delta > 0
      ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
      : delta < 0
        ? "text-rose-400 bg-rose-500/10 border-rose-500/20"
        : "text-(--t-2) bg-(--line-2) border-(--line)";

  return (
    <div className="flex flex-col gap-2 rounded border-0 bg-(--line-2) p-4">
      <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-(--t-3)">
        {icon}
        {label}
      </div>
      <div className="flex items-center gap-3">
        <p className="text-2xl font-black text-(--t-1)">{Math.round(current)}</p>
        {previous !== null ? (
          <div className={cx("rounded-lg border px-2 py-1 text-[10px] font-black", colorClass)}>
            {delta > 0 ? "+" : ""}
            {Math.round(delta)}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function ProjectTimelineClient() {
  const router = useRouter();
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const { getToken, isSignedIn } = useAuth();

  const [projectName, setProjectName] = useState("Project");
  const [projectUrl, setProjectUrl] = useState("");
  const [period, setPeriod] = useState<"30d" | "90d" | "1y" | "all">("90d");
  const [granularity, setGranularity] = useState<"daily" | "weekly" | "monthly">("weekly");
  const [visibleSeries, setVisibleSeries] = useState({
    seo: true,
    geo: true,
    aeo: true,
    volatility: true,
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trends, setTrends] = useState<ProjectTrendResponse | null>(null);
  const [comparison, setComparison] = useState<ProjectTrendComparisonResponse | null>(null);
  const [audits, setAudits] = useState<ProjectAuditHistoryEntry[]>([]);

  const getAuthHeaders = React.useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  useEffect(() => {
    let cancelled = false;

    const loadTimeline = async () => {
      if (!projectId || !isSignedIn) {
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const headers = await getAuthHeaders();
        const [project, trendPayload, comparisonPayload, auditHistory] = await Promise.all([
          fetchProjectById(projectId, headers),
          fetchProjectTrends(projectId, headers, { period, granularity }),
          fetchProjectTrendComparison(projectId, headers, {
            period: resolveComparisonPeriod(period),
          }),
          fetchProjectAudits(projectId, headers, { limit: 12 }),
        ]);

        if (cancelled) {
          return;
        }

        setProjectName(project.name);
        setProjectUrl(normalizeProjectUrl(project.domain_url));
        setTrends(trendPayload);
        setComparison(comparisonPayload);
        setAudits(auditHistory);
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error ? loadError.message : "Unable to load project timeline."
          );
          setTrends(null);
          setComparison(null);
          setAudits([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadTimeline();

    return () => {
      cancelled = true;
    };
  }, [getAuthHeaders, granularity, isSignedIn, period, projectId]);

  const timelineAudits = useMemo(
    () =>
      [...audits].sort(
        (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
      ),
    [audits]
  );

  const hasNoHistoricalData = !loading && timelineAudits.length === 0;

  const handleRunInitialAudit = React.useCallback(() => {
    const query = new URLSearchParams({ projectId });
    if (projectUrl) {
      query.set("url", projectUrl);
    }
    router.push(`/dashboard/audit?${query.toString()}`);
  }, [projectId, projectUrl, router]);

  const toggleSeries = (key: "seo" | "geo" | "aeo" | "volatility") => {
    setVisibleSeries((current) => ({
      ...current,
      [key]: !current[key],
    }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="flex items-center gap-3 text-sm font-black uppercase tracking-widest text-(--purple) animate-pulse">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading trend intelligence...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <GlassCard className="p-8">
        <p className="text-sm font-semibold text-rose-300">{error}</p>
      </GlassCard>
    );
  }

  if (hasNoHistoricalData) {
    return (
      <GlassCard className="flex flex-col items-center justify-center border-(--line) bg-(--line-2) p-12 text-center">
        <GitCommitHorizontal className="mb-4 h-12 w-12 text-(--t-3)" />
        <h3 className="mb-2 text-lg font-black tracking-tight text-(--t-1)">
          No Trend History Yet
        </h3>
        <p className="mb-6 max-w-md text-sm font-medium text-(--t-2)">
          {projectName} does not have enough completed assessments to build trend analytics. Run the
          first audit to create a baseline and unlock month-over-month reporting.
        </p>
        <Button variant="primary" onClick={handleRunInitialAudit}>
          Begin Initial Assessment <ArrowRight className="ml-2 h-4 w-4" />
        </Button>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-8">
      <GlassCard className="overflow-hidden border-(--line) bg-(--panel) p-8">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--purple)">
              Historical Trends
            </p>
            <h3 className="mt-3 text-3xl font-black tracking-tight text-(--t-1)">
              Proof of movement for {projectName}
            </h3>
            <p className="mt-3 text-sm leading-7 text-(--t-2)">
              Compare score movement over time, inspect momentum by channel, and overlay the global
              AI search volatility line to explain sudden market turbulence in monthly reporting.
            </p>
          </div>

          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              {PERIOD_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setPeriod(option.value)}
                  className={cx(
                    "rounded-full border px-4 py-2 text-[10px] font-black uppercase tracking-[0.2em] transition",
                    period === option.value
                      ? "border-[color-mix(in_srgb,var(--purple)_40%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] text-indigo-300"
                      : "border-(--line) bg-(--line-2) text-(--t-3) hover:border-(--line) hover:text-(--t-2)"
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap gap-2">
              {GRANULARITY_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setGranularity(option.value)}
                  className={cx(
                    "rounded-full border px-4 py-2 text-[10px] font-black uppercase tracking-[0.2em] transition",
                    granularity === option.value
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-(--line) bg-(--line-2) text-(--t-3) hover:border-(--line) hover:text-(--t-2)"
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          {[
            { key: "seo" as const, label: "SEO", color: "text-(--purple)" },
            { key: "geo" as const, label: "AI visibility", color: "text-indigo-300" },
            { key: "aeo" as const, label: "AI answers", color: "text-amber-300" },
            { key: "volatility" as const, label: "AI Volatility", color: "text-rose-300" },
          ].map((series) => (
            <button
              key={series.key}
              type="button"
              onClick={() => toggleSeries(series.key)}
              className={cx(
                "rounded-full border px-4 py-2 text-[10px] font-black uppercase tracking-[0.2em] transition",
                visibleSeries[series.key]
                  ? "border-white/15 bg-(--line-2) text-(--t-1)"
                  : "border-(--line) bg-(--line-2) text-(--t-3)"
              )}
            >
              <span className={series.color}>{series.label}</span>
            </button>
          ))}
        </div>

        <div className="mt-8">
          <ProjectTrendChart data={trends?.data_points ?? []} visibleSeries={visibleSeries} />
        </div>
      </GlassCard>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <ScoreMovementCard label="SEO vs previous period" value={comparison?.delta.seo ?? null} />
        <ScoreMovementCard
          label="AI visibility vs previous period"
          value={comparison?.delta.geo ?? null}
        />
        <ScoreMovementCard
          label="AI answers vs previous period"
          value={comparison?.delta.aeo ?? null}
        />
        <ScoreMovementCard label="Overall momentum" value={comparison?.delta.overall ?? null} />
      </div>

      <GlassCard className="border-(--line) bg-(--panel) p-8">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--t-3)">
              Audit Trail
            </p>
            <h3 className="mt-2 text-2xl font-black tracking-tight text-(--t-1)">
              Recent checkpoints behind the trendline
            </h3>
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-(--t-3)">
            {timelineAudits.length} audits in history
          </p>
        </div>

        <div className="mt-8 space-y-5">
          {timelineAudits.map((audit, index) => {
            const previousAudit = timelineAudits[index + 1] ?? null;

            return (
              <motion.div
                key={audit.id}
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.06 }}
              >
                <GlassCard className="border-(--line) bg-(--line-2) p-6">
                  <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-xs font-black uppercase tracking-[0.2em] text-(--purple)">
                        {formatDateTime(audit.created_at)}
                      </p>
                      <p className="mt-2 text-sm font-semibold text-(--t-2)">
                        {audit.audit_type} audit
                      </p>
                    </div>
                    <Button
                      variant="inverse"
                      size="sm"
                      className="h-9 px-4"
                      onClick={() => router.push(`/dashboard/audit/${audit.id}`)}
                    >
                      View Report
                    </Button>
                  </div>

                  <div className="mt-6 grid gap-4 md:grid-cols-3">
                    <AuditScoreBadge
                      label="SEO"
                      icon={<Search className="h-3.5 w-3.5" />}
                      current={audit.seo_score}
                      previous={previousAudit?.seo_score ?? null}
                    />
                    <AuditScoreBadge
                      label="AI visibility"
                      icon={<GeoIcon className="h-3.5 w-3.5" />}
                      current={audit.geo_score}
                      previous={previousAudit?.geo_score ?? null}
                    />
                    <AuditScoreBadge
                      label="AI answers"
                      icon={<Sparkles className="h-3.5 w-3.5" />}
                      current={audit.aeo_score}
                      previous={previousAudit?.aeo_score ?? null}
                    />
                  </div>
                </GlassCard>
              </motion.div>
            );
          })}
        </div>
      </GlassCard>
    </div>
  );
}
