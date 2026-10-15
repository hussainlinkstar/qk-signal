"use client";

import React from "react";
import { ChevronRight, Activity, Target, Award, Info } from "lucide-react";
import GeoIcon from "@/components/ui/GeoIcon";
import Tooltip from "@/components/ui/Tooltip";
import ScoreGauge from "@/components/results/ScoreGauge";
import ScoreDeltaBadge from "@/components/results/ScoreDeltaBadge";
import ScoreHistorySparkline from "@/components/results/ScoreHistorySparkline";
import DetailedSignalList from "@/components/results/DetailedSignalList";
import ScoreBreakdownAccordion from "@/components/results/ScoreBreakdownAccordion";
import RecommendationsList from "@/components/results/RecommendationsList";
import AdvisorPanel from "@/components/results/AdvisorPanel";
import AdvisorChat from "@/components/results/AdvisorChat";
import ExecutionPanel from "@/components/results/ExecutionPanel";
import EnginePanel from "@/components/results/EnginePanel";
import DeepAnalysis from "@/components/results/DeepAnalysis";
import IntegrityStatusBanner from "@/components/results/IntegrityStatusBanner";
import PillarCard from "@/components/results/PillarCard";
import AioBreakdown from "@/components/results/AioBreakdown";
import { getScoreColor } from "@/lib/scoreColors";
import {
  toScoreValue,
  getPillars,
  getAioView,
  getConsolidatedFixes,
  getSearchTypes,
} from "@/lib/reportAdapters";
import type { CanonicalAuditReport, DetailedRecommendation } from "@/lib/reportAdapters";
import type { AuditComparisonResponse } from "@/hooks/useAuditComparison";
import type { RoleMode } from "@/lib/roleMode";
import { describeScore } from "@/lib/copy/signalCopy";
import { cx } from "@/components/ui/utils";

// SIGV2-1168: the done-for-you execution upsell is withdrawn, not offered in
// the MVP. The panel is presentational only, and the entitlement behind it
// unlocks a read-only Advisor plan-progress view rather than execution; no
// approved mockup draws it. The component stays fully working and flipping
// this flag restores the teaser once execution genuinely ships.
const SHOW_DONE_FOR_YOU_EXECUTION = false;

type OverviewTabProps = {
  report: CanonicalAuditReport;
  overallScore: number;
  seoScore: number;
  aeoScore: number;
  geoScore: number;
  performance: Record<string, any>;
  network: Record<string, any>;
  structuredDataDetected: boolean | undefined;
  seoStatus: string | undefined;
  scoreGroups: Array<{ label: string; score: number }>;
  allRecommendations: DetailedRecommendation[];
  aeoTabData: Record<string, any> | null;
  geoTabData: Record<string, any> | null;
  readOnly?: boolean;
  projectId?: string | number | null;
  /**
   * The active audit's id. Threaded to the grounded Advisor chat so it can
   * answer questions about THIS audit. Absent (e.g. archived/guest) hides the
   * chat. Sourced from `activeAuditMeta?.id` in `AuditWorkspace`.
   */
  auditId?: string | number | null;
  comparisonData?: AuditComparisonResponse;
  sampleMode?: boolean;
  isBrandWithoutUrl?: boolean;
  onNavigateToTab?: (tab: string) => void;
  /** Active persona role mode — gates whether raw SEO/AEO/GEO numbers show as a headline. */
  roleMode?: RoleMode;
  /** Existing AEO tab content, rendered inside the AIO drilldown. */
  aeoPanel?: React.ReactNode;
  /** Existing GEO tab content, rendered inside the AIO drilldown. */
  geoPanel?: React.ReactNode;
  /** Whether the plan may see the premium Comparison search type (else gated). */
  canSeeComparison?: boolean;
  /**
   * Whether the plan may see the Advisor's full AI recommendations (Standard+).
   * Defaults to `false` (fail-safe) so the Advisor panel stays blurred behind
   * the upsell when the capability is unknown or the prop is omitted.
   */
  canSeeAdvisor?: boolean;
  /**
   * Whether the plan may see the done-for-you execution panel (Executive+).
   * Defaults to `false` (fail-safe) so the panel stays blurred behind the
   * upsell when the capability is unknown or the prop is omitted.
   */
  canSeeExecution?: boolean;
  /** Forwarded to the gated upsell CTA for guest audits. */
  guestAuditToken?: string;
};

const MetricsGridCard = ({ label, score, helper, icon: Icon, tooltip, delta, onClick }: any) => {
  const scoreColor = typeof score === "number" ? getScoreColor(score) : null;
  const scoreTextClass = scoreColor ? scoreColor.text : "text-(--t-1)";

  return (
    <div
      className={cx("relative group", onClick && "cursor-pointer")}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e: React.KeyboardEvent) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="relative flex flex-col justify-between p-6 rounded border-0 bg-white h-full hover:bg-(--line-2) transition-all duration-500 overflow-visible">
        {tooltip && (
          <div className="absolute top-2 right-2 z-60">
            <Tooltip
              content={<div className="font-medium whitespace-normal text-left">{tooltip}</div>}
            >
              <Info className="w-4 h-4 text-[color-mix(in_srgb,var(--t-3)_70%,transparent)] cursor-help hover:text-(--t-1) transition-colors" />
            </Tooltip>
          </div>
        )}
        <div className="flex items-start justify-between">
          <div className="flex flex-col gap-1 pr-8">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
              {label}
            </span>
            <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              {helper}
            </span>
          </div>
          <div
            className={cx(
              "p-2 rounded-xl border-0 bg-white",
              scoreColor ? scoreColor.text : "text-(--t-2)"
            )}
          >
            <Icon className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-6 flex items-baseline gap-2">
          <span
            className={cx(
              "text-3xl font-black score-glow transition-all duration-500",
              scoreTextClass
            )}
            style={
              scoreColor
                ? ({ "--score-glow-color": `${scoreColor.hex}40` } as React.CSSProperties)
                : undefined
            }
          >
            {score}
          </span>
          <span className="text-xs font-black text-(--t-3)">/100</span>
          {delta && (
            <ScoreDeltaBadge
              delta={delta.delta}
              direction={delta.direction}
              previousScore={delta.previous}
            />
          )}
          {onClick && (
            <ChevronRight className="ml-auto w-4 h-4 text-(--t-3) opacity-0 group-hover:opacity-100 transition-opacity" />
          )}
        </div>
      </div>
    </div>
  );
};

export default function OverviewTab({
  report,
  overallScore,
  seoScore,
  aeoScore,
  geoScore,
  performance = {},
  network: _network = {},
  structuredDataDetected: _structuredDataDetected,
  seoStatus: _seoStatus,
  scoreGroups,
  allRecommendations,
  aeoTabData,
  geoTabData,
  readOnly,
  projectId,
  auditId,
  comparisonData,
  sampleMode,
  isBrandWithoutUrl,
  onNavigateToTab,
  roleMode = "marketer",
  aeoPanel,
  geoPanel,
  canSeeComparison = false,
  canSeeAdvisor = false,
  canSeeExecution = false,
  guestAuditToken,
}: OverviewTabProps) {
  const hasPrevious = comparisonData?.has_previous ?? false;
  const scores = comparisonData?.scores;

  const isSpecialist = roleMode === "specialist";
  const pillars = React.useMemo(() => getPillars(report), [report]);
  const aioView = React.useMemo(() => getAioView(report), [report]);
  const searchTypes = React.useMemo(() => getSearchTypes(report), [report]);
  // SIGV2-1193: one consolidated list, shared with the report's fix rows
  // and the project's action plan page.
  const fixes = React.useMemo(() => getConsolidatedFixes(report), [report]);
  const [showAioBreakdown, setShowAioBreakdown] = React.useState(false);

  return (
    <div className="space-y-12 pb-12">
      {/* Two-pillar headline — SEO (website) + AIO (website & brand roll-up). */}
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {pillars.map((pillar) => {
            // Deterministic, role-appropriate copy for each pillar score.
            // Numbers stay as X/100 in PillarCard; this adds the
            // human-readable interpretation + next action per role.
            const copy = describeScore(pillar.key, pillar.score, roleMode);
            return (
              <PillarCard
                key={pillar.key}
                pillar={pillar}
                isActive={pillar.key === "aio" ? showAioBreakdown : false}
                language={copy.interpretation}
                nextAction={copy.nextAction}
                onClick={
                  pillar.key === "seo"
                    ? onNavigateToTab
                      ? () => onNavigateToTab("seo")
                      : undefined
                    : () => setShowAioBreakdown((open) => !open)
                }
              />
            );
          })}
        </div>
        <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
          Click SEO or AIO to see the detailed breakdown.
        </p>
      </div>

      {/* AIO drilldown — groups the AEO + GEO panels under one view. */}
      {showAioBreakdown && (
        <AioBreakdown
          aioView={aioView}
          role={roleMode}
          aeoPanel={aeoPanel}
          geoPanel={geoPanel}
          searchTypes={searchTypes}
          canSeeComparison={canSeeComparison}
          guestAuditToken={guestAuditToken}
        />
      )}

      {/* Live engine tracking, mounted near the AIO surface. No plan gate: the
                backend grants `has_live_engine_tracking` on every plan
                (SIGV2-1108). */}
      <EnginePanel />

      {/* Specialist mode retains the raw SEO/AEO/GEO + Performance gauges. */}
      {isSpecialist && (
        <div
          className={cx(
            "grid gap-4",
            isBrandWithoutUrl
              ? "grid-cols-2 md:grid-cols-4"
              : "grid-cols-2 md:grid-cols-3 xl:grid-cols-5"
          )}
        >
          <MetricsGridCard
            label="Overall"
            score={overallScore}
            helper="Overall Score"
            icon={Activity}
            tooltip="Aggregated score combining SEO and AIO performance into a single overall score."
            delta={hasPrevious ? scores?.overall : undefined}
          />
          <MetricsGridCard
            label="SEO"
            score={seoScore}
            helper="Search Visibility"
            icon={Target}
            tooltip="Measures technical health, on-page optimization, and core web vitals for traditional search visibility."
            delta={hasPrevious ? scores?.seo : undefined}
            onClick={onNavigateToTab ? () => onNavigateToTab("seo") : undefined}
          />
          <MetricsGridCard
            label="AI answers"
            score={aeoScore}
            helper="Answer Readiness"
            icon={Award}
            tooltip="Evaluates query answerability, schema health, and LLM readiness for AI Overviews and Voice Search."
            delta={hasPrevious ? scores?.aeo : undefined}
            onClick={onNavigateToTab ? () => onNavigateToTab("aeo") : undefined}
          />
          <MetricsGridCard
            label="AI visibility"
            score={geoScore}
            helper="AI Citation Share"
            icon={GeoIcon}
            tooltip="Assesses brand visibility, entity matching, and citation share across AI search engines."
            delta={hasPrevious ? scores?.geo : undefined}
            onClick={onNavigateToTab ? () => onNavigateToTab("geo") : undefined}
          />

          {!isBrandWithoutUrl && (
            <div className="relative group h-full">
              <div className="relative flex flex-col items-center justify-center p-4 rounded border-0 bg-white h-full hover:bg-(--line-2) transition-all duration-500">
                <div className="absolute top-2 right-2 z-10">
                  <Tooltip
                    content={
                      <div className="font-medium whitespace-normal text-left">
                        Aggregated lab performance score based on LCP, CLS, and core web vitals
                        metrics.
                      </div>
                    }
                  >
                    <Info className="w-3.5 h-3.5 text-(--t-3) cursor-help hover:text-(--t-1) transition-colors" />
                  </Tooltip>
                </div>
                <ScoreGauge
                  score={toScoreValue(performance.performance_score)}
                  label="Performance"
                  animate={readOnly}
                  size={80}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Score History Sparkline */}
      {comparisonData?.history && comparisonData.history.length >= 2 && (
        <div className="rounded border-0 bg-white p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
              Score Trend ({comparisonData.history.length} audits)
            </span>
            {!hasPrevious && (
              <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                First audit, no comparison available
              </span>
            )}
          </div>
          <ScoreHistorySparkline
            data={comparisonData.history}
            dataKey="overall"
            color="var(--chart-1)"
            height={56}
          />
        </div>
      )}

      <div className="space-y-10">
        {report.debate_findings && report.debate_findings.length > 0 && (
          <div className="relative">
            <DeepAnalysis
              grid={report.debate_findings}
              executiveSummary={report.strategic_summary ?? report.neural_executive_summary}
              competitivePositioning={report.competitive_positioning}
              generativeMetrics={report.generative_authority_metrics}
            />
          </div>
        )}

        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <h3 className="font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1) flex items-center gap-3">
              <ChevronRight className="w-4 h-4 text-primary" />
              Score Breakdown
            </h3>
            <div className="h-px flex-1 bg-(--line-2)" />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
            <div className="space-y-4">
              <ScoreBreakdownAccordion
                title="SEO Granular Breakdown"
                overallScore={seoScore}
                defaultOpen
                isBrandWithoutUrl={isBrandWithoutUrl}
                subScores={(() => {
                  const rawComponents = (report as any).scores?.seo_breakdown?.components ?? {};
                  const hiddenKeys = isBrandWithoutUrl
                    ? new Set(["core_web_vitals", "technical_seo", "security_accessibility"])
                    : new Set<string>();
                  const entries = Object.entries(rawComponents).filter(
                    ([key]) => !hiddenKeys.has(key)
                  );
                  const canonicalWeights: Record<string, number> = isBrandWithoutUrl
                    ? { onpage_content: 0.4, eeat_trust: 0.6 }
                    : {
                        core_web_vitals: 0.25,
                        technical_seo: 0.2,
                        onpage_content: 0.2,
                        eeat_trust: 0.2,
                        security_accessibility: 0.15,
                      };
                  const presentKeys = entries.map(([k]) => k);
                  const rawSum = presentKeys.reduce((s, k) => s + (canonicalWeights[k] ?? 0), 0);
                  return entries.map(([key, score]) => ({
                    key,
                    label: key,
                    score: Number(score) || 0,
                    weight: rawSum > 0 ? (canonicalWeights[key] ?? 0) / rawSum : 0,
                  }));
                })()}
              />
              {isSpecialist && (
                <ScoreBreakdownAccordion
                  title="AI visibility granular breakdown"
                  overallScore={geoScore}
                  isBrandWithoutUrl={isBrandWithoutUrl}
                  subScores={Object.entries(
                    (report as any).scores?.geo_breakdown?.components ?? {}
                  ).map(([key, score]) => ({
                    key,
                    label: key,
                    score: Number(score) || 0,
                    weight:
                      (
                        {
                          content_citability: 0.3,
                          source_authority: 0.25,
                          entity_clarity: 0.25,
                          brand_citation: 0.2,
                        } as Record<string, number>
                      )[key] ?? 0,
                  }))}
                />
              )}
              {isSpecialist && (
                <ScoreBreakdownAccordion
                  title="AI answers granular breakdown"
                  overallScore={aeoScore}
                  isBrandWithoutUrl={isBrandWithoutUrl}
                  subScores={Object.entries(
                    (report as any).scores?.aeo_breakdown?.components ?? {}
                  ).map(([key, score]) => ({
                    key,
                    label: key,
                    score: Number(score) || 0,
                    weight:
                      (
                        {
                          llm_schema_readiness: 0.3,
                          semantic_entity_density: 0.25,
                          information_gain: 0.25,
                          snippet_formatting: 0.2,
                        } as Record<string, number>
                      )[key] ?? 0,
                  }))}
                />
              )}
            </div>
            {isSpecialist && !isBrandWithoutUrl && (
              <div className="space-y-4">
                <DetailedSignalList
                  title="AI answers intelligence"
                  signals={[
                    {
                      label: "Answerability",
                      score: aeoTabData?.scoreDetails?.answerability_score ?? 0,
                      description: "Direct response alignment",
                    },
                    {
                      label: "Voice Readiness",
                      score: aeoTabData?.scoreDetails?.voice_readiness_score ?? 0,
                      description: "Voice search optimization",
                    },
                    {
                      label: "Schema Completeness",
                      score: aeoTabData?.scoreDetails?.schema_completeness ?? 0,
                      description: "Structured data coverage",
                    },
                    {
                      label: "Content Freshness",
                      score: aeoTabData?.scoreDetails?.content_freshness_score ?? 0,
                      description: "Content recency and update frequency",
                    },
                  ]}
                />
                <DetailedSignalList
                  title="AI visibility citations"
                  signals={[
                    {
                      label: "Local Authority",
                      score: geoTabData?.scoreDetails?.local_authority_score ?? 0,
                      description: "Regional presence and trust",
                    },
                    {
                      label: "Citation Consistency",
                      score: geoTabData?.scoreDetails?.citation_consistency_score ?? 0,
                      description: "NAP accuracy across the web",
                    },
                    {
                      label: "Search Relevance",
                      score: geoTabData?.scoreDetails?.relevance_score ?? 0,
                      description: "Topical alignment with user search intent",
                    },
                  ]}
                />
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
          {/* Score Breakdown Row */}
          <div className="space-y-6">
            <div className="flex items-center gap-4">
              <h3 className="font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1) flex items-center gap-3">
                <ChevronRight className="w-4 h-4 text-primary" />
                Score Distribution
              </h3>
              <div className="h-px flex-1 bg-(--line-2)" />
            </div>

            {scoreGroups.length > 0 ? (
              <>
                <div className="flex items-center overflow-x-auto gap-4 pb-2 no-scrollbar">
                  {scoreGroups.map((group) => (
                    <div
                      key={group.label}
                      className="p-4 min-w-[140px] shrink-0 rounded border-0 hover:bg-(--line-2) transition-colors flex items-center justify-center"
                    >
                      <ScoreGauge
                        score={group.score}
                        label={group.label}
                        animate={readOnly}
                        size={80}
                      />
                    </div>
                  ))}
                </div>
                {/* Only true for the SEO/GEO/AEO breakdown (not the legacy
                                    Citability/Entity Match/Trust Signals/Technical SEO groups),
                                    so these per-axis gauges aren't read as a fourth, disconnected
                                    score next to the SEO/AIO pillars above. */}
                {scoreGroups.some((group) => group.label === "AI Visibility Score") &&
                  scoreGroups.some((group) => group.label === "AI Answers Index") && (
                    <p className="text-[11px] leading-relaxed text-(--t-3)">
                      AI Visibility Score and AI Answers Index roll up into your AIO score above.
                    </p>
                  )}
              </>
            ) : (
              <div className="p-8 rounded border border-dashed border-(--line) text-center">
                <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                  No Score Data Available
                </p>
              </div>
            )}
          </div>

          {!isBrandWithoutUrl && (
            <div className="space-y-6">
              <div className="flex items-center gap-4">
                <h3 className="font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1) flex items-center gap-3">
                  <ChevronRight className="w-4 h-4 text-primary" />
                  Technical Signals
                </h3>
                <div className="h-px flex-1 bg-(--line-2)" />
              </div>
              <DetailedSignalList
                title="Technical Vitals"
                signals={[
                  {
                    label: "Performance",
                    score: report.technical_signals?.performance?.score ?? 0,
                    description: "Page loading and rendering speed",
                  },
                  {
                    label: "HTTP Protocol",
                    score: report.technical_signals?.network?.supports_http2 ? 100 : 0,
                    description: "HTTP/2+ support status",
                  },
                  {
                    label: "Layout Stability",
                    score:
                      report.technical_signals?.performance?.cls !== undefined &&
                      report.technical_signals?.performance?.cls !== null
                        ? Math.max(0, 100 - report.technical_signals.performance.cls * 100)
                        : 0,
                    description: "Cumulative Layout Shift (CLS) score",
                  },
                ]}
              />
            </div>
          )}
        </div>

        <IntegrityStatusBanner report={report} className="mt-8" />

        {/* Deterministic, ROI-ranked Advisor plan ("what to fix, in order").
                    Gated to Standard+ via `canSeeAdvisor` (Phase 5): the panel still
                    renders for Free as a blurred upsell teaser. Fail-safe LOCKED. */}
        {fixes.length > 0 && (
          <div className="pt-8">
            <AdvisorPanel
              fixes={fixes}
              isLocked={!canSeeAdvisor}
              guestAuditToken={guestAuditToken}
              projectId={projectId}
            />
          </div>
        )}

        {/* Conversational, audit-grounded advisor chat. Gated to Standard+
                    via `canSeeAdvisor` (Phase 5) — blurred upsell for Free. Hidden
                    when there's no audit to ground on. Fail-safe LOCKED. */}
        <AdvisorChat
          auditId={auditId}
          isLocked={!canSeeAdvisor}
          guestAuditToken={guestAuditToken}
          className="pt-8"
        />

        {/* Done-for-you execution summary (Executive+). Withdrawn offer, see
                    SHOW_DONE_FOR_YOU_EXECUTION above: rendered for every tier as a
                    blurred upsell teaser when `canSeeExecution` is false.
                    Fail-safe LOCKED. */}
        {SHOW_DONE_FOR_YOU_EXECUTION ? (
          <div className="pt-8">
            <ExecutionPanel isLocked={!canSeeExecution} guestAuditToken={guestAuditToken} />
          </div>
        ) : null}

        {allRecommendations.length > 0 && (
          <div className="relative pt-8">
            <div className="absolute inset-0 bg-primary/5 blur-3xl rounded-(--r) -z-10" />
            <div className="flex items-center gap-4 mb-8">
              <h3 className="font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1) flex items-center gap-3">
                <ChevronRight className="w-4 h-4 text-primary" />
                Priority Recommendations
              </h3>
              <div className="h-px flex-1 bg-(--line-2)" />
            </div>
            <div className="pt-2">
              <RecommendationsList
                recommendations={allRecommendations}
                projectId={projectId}
                siteUrl={report.url ?? report.analysis?.url ?? null}
                sampleMode={sampleMode}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
