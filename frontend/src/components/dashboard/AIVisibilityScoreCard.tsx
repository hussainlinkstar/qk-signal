"use client";

import React from "react";
import { AlertCircle, Bot, Eye } from "lucide-react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import {
  CARD_CONTAINER_PRESETS,
  CARD_LABEL_CLASS,
  CARD_SUBSECTION_SURFACE_CLASS,
  DASHBOARD_CARD_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import Tooltip from "@/components/ui/Tooltip";
import { getScoreColor } from "@/lib/scoreColors";
import type { ScoreBreakdown, VisibilitySummaryResponse } from "@/types/monitoring";
import {
  VISIBILITY_PROVIDER_LABELS,
  formatVisibilityPercent,
  isMeasuredVisibilityProvider,
} from "@/components/dashboard/visibilityUtils";
import { ScoreIconTile, ScoreMetricTile, ScoreToneBadge, TrendChip } from "./scorePrimitives";

const BREAKDOWN_LABELS: Record<keyof ScoreBreakdown, { label: string; max: number }> = {
  citation_presence: { label: "Citations", max: 40 },
  citation_position: { label: "Position", max: 20 },
  text_mention: { label: "Mentions", max: 20 },
  topic_relevance: { label: "Relevance", max: 20 },
};

function BreakdownTooltipContent({ breakdown }: { breakdown: ScoreBreakdown }) {
  return (
    <div className="space-y-1.5 text-xs">
      <p className="font-medium text-(--foreground)">Score Breakdown</p>
      {(Object.keys(BREAKDOWN_LABELS) as (keyof ScoreBreakdown)[]).map((key) => {
        const { label, max } = BREAKDOWN_LABELS[key];
        const value = breakdown[key] ?? 0;
        const pct = max > 0 ? Math.round((value / max) * 100) : 0;
        return (
          <div key={key} className="flex items-center gap-2">
            <span className="w-16 text-(--text-muted)">{label}</span>
            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full w-(--bw) rounded-full bg-(--primary)"
                style={{ "--bw": `${pct}%` } as React.CSSProperties}
              />
            </div>
            <span className="tabular-nums text-(--text-soft)">
              {value}/{max}
            </span>
          </div>
        );
      })}
    </div>
  );
}

type AIVisibilityScoreCardProps = {
  summary: VisibilitySummaryResponse | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
};

function LoadingState() {
  return (
    <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
      <div className="animate-pulse space-y-6">
        <div className="space-y-2">
          <div className="h-3 w-28 rounded bg-white/10" />
          <div className="h-8 w-56 rounded bg-white/10" />
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className={`${CARD_SUBSECTION_SURFACE_CLASS} h-24`} />
          ))}
        </div>
      </div>
    </Card>
  );
}

export default function AIVisibilityScoreCard({
  summary,
  loading = false,
  error = null,
  onRetry,
}: AIVisibilityScoreCardProps) {
  if (loading) {
    return <LoadingState />;
  }

  if (error) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <p className={CARD_LABEL_CLASS}>AI Visibility</p>
            <h2 className={TYPO.sectionTitle}>AI Visibility Score</h2>
            <p className="text-sm text-(--text-soft)">{error}</p>
          </div>
          <AlertCircle className="h-5 w-5 text-warning" />
        </div>
        {onRetry ? (
          <Button size="sm" variant="ghost" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
      </Card>
    );
  }

  if (!summary || summary.queries_configured === 0) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="flex items-start gap-4">
          <ScoreIconTile level="warning">
            <Eye className="h-5 w-5" />
          </ScoreIconTile>
          <div className="space-y-2">
            <p className={CARD_LABEL_CLASS}>AI Visibility</p>
            <h2 className={TYPO.sectionTitle}>AI Visibility Score</h2>
            <p className="text-sm text-(--text-soft)">
              Add queries to track where your brand appears in AI-generated answers.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const score = summary.visibility_score;
  const tone = getScoreColor(score);
  const trendDelta = summary.trend_delta;
  const hasCompletedChecks = summary.completed_checks > 0;

  return (
    <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`} glow>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1.2fr)] xl:items-start">
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <ScoreIconTile level={tone.level}>
              <Bot className="h-5 w-5" />
            </ScoreIconTile>
            <div>
              <p className={CARD_LABEL_CLASS}>AI Visibility</p>
              <h2 className={TYPO.sectionTitle}>AI Visibility Score</h2>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              {summary.score_breakdown && hasCompletedChecks ? (
                <Tooltip
                  content={<BreakdownTooltipContent breakdown={summary.score_breakdown} />}
                  side="bottom"
                  panelClassName="max-w-72"
                  triggerAriaLabel="View visibility score breakdown"
                >
                  <p className={`cursor-help text-5xl font-semibold tracking-tight ${tone.text}`}>
                    {formatVisibilityPercent(score)}
                  </p>
                </Tooltip>
              ) : (
                <p className={`text-5xl font-semibold tracking-tight ${tone.text}`}>
                  {hasCompletedChecks ? formatVisibilityPercent(score) : "Pending"}
                </p>
              )}
              {hasCompletedChecks ? <ScoreToneBadge score={score} /> : null}
            </div>
            <p className="max-w-xl text-sm leading-6 text-(--text-soft)">
              Your brand appears in{" "}
              {hasCompletedChecks ? formatVisibilityPercent(score) : "pending"} of tracked
              AI-generated answers.
            </p>
            <TrendChip delta={typeof trendDelta === "number" ? trendDelta : null} />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <ScoreMetricTile
              detail="Across configured prompt sets"
              label="Tracked queries"
              value={summary.queries_configured}
            />
            <ScoreMetricTile
              label="Checks completed"
              value={`${summary.completed_checks}/${summary.total_checks}`}
            />
            <ScoreMetricTile label="Citations found" value={`${summary.cited_checks}`} />
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {/* SIGV2-1215: a withdrawn engine gets no card. A card is a
              measurement claim, and a project that selected Copilot while it
              was offered can still have a row for it in this payload.

              SIGV2-1216: so does an engine this plan has stopped measuring,
              for the same reason and with the same answer. No explanatory row
              stands in for the card: a row saying "we used to measure this"
              is still a claim about an engine nobody re-measures, and the
              plan's own engine list is where that belongs. */}
          {summary.provider_breakdown
            .filter((provider) =>
              isMeasuredVisibilityProvider(
                provider.provider,
                summary.entitlements?.allowed_providers
              )
            )
            .map((provider) => {
              const providerTone = getScoreColor(provider.visibility_score);
              const providerPercent =
                provider.completed_checks > 0
                  ? provider.visibility_score
                  : provider.tracked_queries > 0
                    ? 0
                    : null;
              return (
                <div
                  key={provider.provider}
                  className={`${CARD_SUBSECTION_SURFACE_CLASS} space-y-3`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className={CARD_LABEL_CLASS}>
                        {VISIBILITY_PROVIDER_LABELS[provider.provider]}
                      </p>
                      <p className={`mt-2 text-2xl font-semibold ${providerTone.text}`}>
                        {provider.completed_checks > 0
                          ? formatVisibilityPercent(provider.visibility_score)
                          : "Pending"}
                      </p>
                    </div>
                    <span className="rounded-full border border-(--border) bg-(--surface-elevated) px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-(--text-muted)">
                      {provider.tracked_queries} tracked
                    </span>
                  </div>
                  <div className="space-y-2">
                    <div className="h-2 overflow-hidden rounded-full bg-(--surface-elevated)">
                      <div
                        className={`${providerTone.bg} w-(--bw)`}
                        style={
                          { "--bw": `${Math.max(6, providerPercent ?? 0)}%` } as React.CSSProperties
                        }
                      />
                    </div>
                    <p className="text-xs text-(--text-muted)">
                      {provider.cited_checks}/
                      {provider.completed_checks || provider.tracked_queries} cited
                    </p>
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </Card>
  );
}
