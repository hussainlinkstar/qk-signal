"use client";

import React, { useMemo } from "react";
import { Bot } from "lucide-react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import {
  CARD_CONTAINER_PRESETS,
  CARD_LABEL_CLASS,
  DASHBOARD_CARD_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import { formatDateTime } from "@/lib/dateFormat";
import { getScoreColor } from "@/lib/scoreColors";
import type { EntityAuthoritySummary, EntityAuthorityTrendPoint } from "@/types/entityAuthority";
import {
  MiniSparkline,
  ScoreIconTile,
  ScoreMetricTile,
  ScoreToneBadge,
  TrendChip,
} from "@/components/dashboard/scorePrimitives";

type EntityAuthorityScoreCardProps = {
  summary: EntityAuthoritySummary;
  trendPoints: EntityAuthorityTrendPoint[];
  recomputing: boolean;
  onRecompute: () => void;
};

export default function EntityAuthorityScoreCard({
  summary,
  trendPoints,
  recomputing,
  onRecompute,
}: EntityAuthorityScoreCardProps) {
  const delta = useMemo(() => {
    if (trendPoints.length < 2) {
      return null;
    }
    const previous = trendPoints[trendPoints.length - 2];
    const latest = trendPoints[trendPoints.length - 1];
    return Number((latest.authority_score - previous.authority_score).toFixed(1));
  }, [trendPoints]);

  const scoreValue = Math.max(0, Math.min(100, summary.authority_score));
  const tone = getScoreColor(scoreValue);
  const sparklineValues = trendPoints.map((point) => point.authority_score);

  return (
    <Card
      className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}
      glow
      variant="glass"
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <ScoreIconTile level={tone.level}>
              <Bot className="h-5 w-5" />
            </ScoreIconTile>
            <div>
              <p className={CARD_LABEL_CLASS}>Entity Authority</p>
              <h2 className={TYPO.sectionTitle}>Entity Authority Score</h2>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <p className={`text-5xl font-semibold tracking-tight ${tone.text}`}>
                {scoreValue.toFixed(1)}
              </p>
              <ScoreToneBadge score={scoreValue} />
            </div>
            <TrendChip delta={delta} />
            <p className="text-sm text-(--text-soft)">
              Last computed:{" "}
              <span className="text-(--foreground)">{formatDateTime(summary.computed_at)}</span>
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <ScoreMetricTile label="Target entities" value={summary.target_entities} />
            <ScoreMetricTile label="Detected" value={summary.detected_entities} />
            <ScoreMetricTile label="Gaps" value={summary.gap_count} />
          </div>

          <Button
            className="w-full justify-center sm:w-auto"
            loading={recomputing}
            loadingText="Recomputing..."
            variant="ghost"
            onClick={onRecompute}
          >
            Recompute score
          </Button>
        </div>

        <div className="space-y-3">
          <div>
            <p className={CARD_LABEL_CLASS}>Trend</p>
            <p className="mt-1 text-sm text-(--text-soft)">
              Authority progression across recent snapshots.
            </p>
          </div>
          <MiniSparkline className="h-full" stroke={tone.hex} values={sparklineValues} />
        </div>
      </div>
    </Card>
  );
}
