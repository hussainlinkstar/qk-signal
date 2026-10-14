"use client";

import React, { useMemo, useRef } from "react";
import ScoreGauge from "./ScoreGauge";
import EntityChips from "./EntityChips";
import TechnicalMetrics from "./TechnicalMetrics";
import RecommendationsList from "./RecommendationsList";
import DetailedSignalList from "./DetailedSignalList";
import DebateProcessCard from "./DebateProcessCard";
import { BrainCircuit, ShieldCheck, Globe, AlertTriangle } from "lucide-react";
import { formatIntegrityLabel, getIntegrityStatusSnapshot } from "@/lib/integrityStatus";
import {
  getAuditEntities,
  getDetailedAuditRecommendations,
  filterBrandOnlyRecommendations,
  getAuditScoreGroups,
  type CanonicalAuditReport,
  type DetailedRecommendation,
} from "@/lib/reportAdapters";

type PrioritizedRecommendation = {
  text: string;
  priority: "High" | "Medium";
  reason: string;
};

type TrackBReviewClaim = {
  key: string;
  claimText: string;
  shadowDisposition:
    | "flagged"
    | "needs_manual_review"
    | "manually_approved"
    | "manually_refused"
    | "omitted";
  confidenceBand: string | null;
  judgeResolution: string | null;
  reasonCodes: string[];
};

const getHallucinationSnapshot = (report: CanonicalAuditReport) =>
  getIntegrityStatusSnapshot(report);

const getTrackBReviewClaims = (report: CanonicalAuditReport): TrackBReviewClaim[] => {
  const dualTrackShadow =
    report.metadata &&
    typeof report.metadata.dual_track_shadow === "object" &&
    report.metadata.dual_track_shadow !== null
      ? (report.metadata.dual_track_shadow as Record<string, unknown>)
      : null;
  const claims = Array.isArray(dualTrackShadow?.claims) ? dualTrackShadow.claims : [];

  return claims.flatMap((entry, index) => {
    if (typeof entry !== "object" || entry === null) {
      return [];
    }

    const item = entry as Record<string, unknown>;
    const track = typeof item.track === "string" ? item.track.trim().toLowerCase() : "";
    const shadowDisposition =
      typeof item.shadow_disposition === "string"
        ? item.shadow_disposition.trim().toLowerCase()
        : "";
    const claimText = typeof item.claim_text === "string" ? item.claim_text.trim() : "";

    if (
      track !== "track_b" ||
      !claimText ||
      ![
        "flagged",
        "needs_manual_review",
        "manually_approved",
        "manually_refused",
        "omitted",
      ].includes(shadowDisposition)
    ) {
      return [];
    }

    const reasonCodes = Array.isArray(item.reason_codes)
      ? item.reason_codes.flatMap((code) =>
          typeof code === "string" && code.trim() ? [code.trim().toLowerCase()] : []
        )
      : [];
    const claimId =
      typeof item.claim_id === "string" && item.claim_id.trim()
        ? item.claim_id.trim()
        : `track-b-${index + 1}`;

    return [
      {
        key: claimId,
        claimText,
        shadowDisposition: shadowDisposition as TrackBReviewClaim["shadowDisposition"],
        confidenceBand:
          typeof item.confidence_band === "string" && item.confidence_band.trim()
            ? item.confidence_band.trim().toLowerCase()
            : null,
        judgeResolution:
          typeof item.judge_resolution === "string" && item.judge_resolution.trim()
            ? item.judge_resolution.trim()
            : null,
        reasonCodes,
      },
    ];
  });
};

const prioritizeRecommendations = (
  recommendations: DetailedRecommendation[]
): PrioritizedRecommendation[] => {
  return recommendations.slice(0, 6).map((rec, index) => {
    const isHighPriority = rec.impact === "Critical" || index < 2;
    return {
      text: rec.title,
      priority: isHighPriority ? "High" : "Medium",
      reason: isHighPriority
        ? "Likely to improve trust and AI visibility first."
        : "Supports incremental quality improvements.",
    };
  });
};

const HallucinationGauge = ({
  flaggedClaims,
  totalClaims,
  hasCertificate,
}: {
  flaggedClaims: number;
  totalClaims: number;
  hasCertificate: boolean;
}) => {
  const ratio = totalClaims > 0 ? (flaggedClaims / totalClaims) * 100 : 0;
  const colorClass = ratio === 0 ? "bg-emerald-500" : ratio < 20 ? "bg-amber-500" : "bg-rose-500";
  const textColor =
    ratio === 0 ? "text-emerald-400" : ratio < 20 ? "text-amber-400" : "text-rose-400";
  const label = hasCertificate ? "Integrity Review Ratio" : "Hallucination Risk Ratio";
  const description = hasCertificate
    ? "Claims requiring trust review or blocked by the integrity certificate out of all reviewed claims."
    : "Total flagged claims out of all reviewed AI-generated statements.";

  return (
    <div className="rounded-md border border-(--line) bg-(--line-2) p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-(--t-2)">{label}</span>
        <span className={`font-mono text-sm font-bold ${textColor}`}>
          {flaggedClaims} / {totalClaims} ({Math.round(ratio)}%)
        </span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-(--line-2)">
        <div
          className={`h-full w-(--bw) rounded-full opacity-(--bo) transition-all duration-500 ${colorClass}`}
          style={
            {
              "--bw": `${Math.min(100, Math.max(0, ratio))}%`,
              "--bo": totalClaims === 0 ? 0 : 1,
            } as React.CSSProperties
          }
        />
      </div>
      <p className="mt-2 text-[10px] text-(--t-2)">{description}</p>
    </div>
  );
};

const certaintyTone = (value?: string) => {
  if (value === "high") return "text-emerald-300 border-emerald-500/30 bg-emerald-500/10";
  if (value === "medium") return "text-amber-200 border-amber-500/30 bg-amber-500/10";
  return "text-rose-200 border-rose-500/30 bg-rose-500/10";
};

const trackBDispositionTone = (value: TrackBReviewClaim["shadowDisposition"]) => {
  if (value === "manually_approved") {
    return "text-emerald-100 border-emerald-500/30 bg-emerald-500/10";
  }
  if (value === "manually_refused") {
    return "text-rose-100 border-rose-500/30 bg-rose-500/10";
  }
  if (value === "needs_manual_review") {
    return "text-amber-100 border-amber-500/30 bg-amber-500/10";
  }
  if (value === "flagged") {
    return "text-sky-100 border-sky-500/30 bg-sky-500/10";
  }
  return "text-rose-100 border-rose-500/30 bg-rose-500/10";
};

const formatTrackBDispositionLabel = (value: TrackBReviewClaim["shadowDisposition"]) => {
  if (value === "manually_approved") {
    return "Approved";
  }
  if (value === "manually_refused") {
    return "Refused";
  }
  if (value === "needs_manual_review") {
    return "Needs Manual Review";
  }
  if (value === "flagged") {
    return "Flagged";
  }
  return "Omitted";
};

const AuditReport = ({ report }: { report: CanonicalAuditReport; isLocked?: boolean }) => {
  const analysis = report.analysis ?? {};
  const performanceMetrics = report.performance ?? {};
  const networkAnalysis = report.network ?? {};
  const warnings = report.warnings ?? report.metadata?.warnings ?? [];
  let screenshotUrl: string | undefined = undefined;
  if (report.screenshot_url && report.screenshot_url !== "undefined") {
    screenshotUrl = report.screenshot_url;
  } else if (report.screenshot_base64 && report.screenshot_base64 !== "undefined") {
    screenshotUrl = `data:image/png;base64,${report.screenshot_base64}`;
  }
  const hallucinationSnapshot = useMemo(() => getHallucinationSnapshot(report), [report]);
  const trackBReviewClaims = useMemo(() => getTrackBReviewClaims(report), [report]);
  const reportUrl = report.url ?? analysis?.url;
  const modeLabel =
    (typeof report.metadata?.mode_label === "string" && report.metadata.mode_label.trim()) ||
    (report.debate?.profile === "high_confidence"
      ? "High Confidence / Prescriptive Confidence mode"
      : "");

  const scoreGroups = useMemo(() => getAuditScoreGroups(report), [report]);
  const overallScore = useMemo(() => {
    if (!scoreGroups.length) return 0;
    const total = scoreGroups.reduce((acc, item) => acc + item.score, 0);
    return Math.round(total / scoreGroups.length);
  }, [scoreGroups]);
  const recommendations = useMemo(() => {
    const raw = getDetailedAuditRecommendations(report);
    const rawReport = report as Record<string, any>;
    const targetType = rawReport.target?.type || rawReport.audit_target_type;
    const targetUrl = rawReport.target?.url || rawReport.site?.url || rawReport.url;
    if (targetType === "brand" && !targetUrl) {
      return filterBrandOnlyRecommendations(raw);
    }
    return raw;
  }, [report]);
  const prioritizedRecommendations = useMemo(
    () => prioritizeRecommendations(recommendations),
    [recommendations]
  );
  const entities = useMemo(() => {
    if (Array.isArray(report.entities)) {
      return report.entities
        .filter(
          (entity): entity is string => typeof entity === "string" && entity.trim().length > 0
        )
        .map((entity) => ({ name: entity.trim(), type: "Entity", confidence: null }));
    }

    return getAuditEntities(report).map((entity) => ({
      name: entity.name,
      type: entity.type,
      confidence: entity.relevance,
    }));
  }, [report]);
  const entitySummary =
    analysis?.entity_data?.summary ?? analysis?.entity_summary ?? analysis?.entity_data?.overview;
  const reportRef = useRef<HTMLDivElement>(null);
  const highPriorityCount = prioritizedRecommendations.filter(
    (item) => item.priority === "High"
  ).length;
  const averageScore = scoreGroups.length
    ? Math.round(scoreGroups.reduce((sum, group) => sum + group.score, 0) / scoreGroups.length)
    : 0;

  return (
    <>
      <div
        id="full-audit-report-container"
        ref={reportRef}
        className="p-4 sm:p-8 bg-surface rounded-xl border border-surface-border"
      >
        <div className="text-center mb-10">
          <h2 className="text-3xl font-bold text-(--t-1)">Entity Assessment Report</h2>
          <p className="text-(--t-2) mt-2">
            A comprehensive analysis of your page's AIO performance.
          </p>
          {modeLabel ? (
            <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[color-mix(in_srgb,var(--purple)_20%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] px-4 py-2">
              <BrainCircuit className="h-4 w-4 text-(--purple)" />
              <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan-100">
                Assessment mode: {modeLabel}
              </span>
            </div>
          ) : null}
        </div>

        <section className="mb-8 rounded-xl border border-(--line) bg-(--line-2) p-4 sm:p-6">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h3 className="text-xl font-semibold text-(--t-1)">Current Status vs Improvements</h3>
              <p className="text-sm text-(--t-2)">
                Scan this section first to understand where you are and what to do next.
              </p>
            </div>
            <div className="text-xs uppercase tracking-wide text-(--t-3)">30-second overview</div>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-(--line) bg-(--line-2) p-5">
              <h4 className="text-sm font-semibold uppercase tracking-wide text-thoth-brass">
                Current Metrics
              </h4>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-md border border-(--line) bg-(--line-2) p-3">
                  <p className="text-xs text-(--t-2)">Overall Score</p>
                  <p className="text-xl font-bold text-(--t-1)">{overallScore}/100</p>
                </div>
                <div className="rounded-md border border-(--line) bg-(--line-2) p-3">
                  <p className="text-xs text-(--t-2)">Average Subscore</p>
                  <p className="text-xl font-bold text-(--t-1)">{averageScore}/100</p>
                </div>
                <div className="rounded-md border border-(--line) bg-(--line-2) p-3">
                  <p className="text-xs text-(--t-2)">Entities Detected</p>
                  <p className="text-xl font-bold text-(--t-1)">{entities.length}</p>
                </div>
                <div className="rounded-md border border-(--line) bg-(--line-2) p-3">
                  <p className="text-xs text-(--t-2)">Warnings</p>
                  <p className="text-xl font-bold text-(--t-1)">{warnings.length}</p>
                </div>
              </div>
            </div>
            <div className="rounded-lg border border-(--line) bg-(--line-2) p-5">
              <div className="flex items-center justify-between gap-3">
                <h4 className="text-sm font-semibold uppercase tracking-wide text-thoth-logic">
                  Prioritized Improvements
                </h4>
                <span className="rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-xs font-medium text-amber-200">
                  {highPriorityCount} high priority
                </span>
              </div>
              <ul className="mt-4 space-y-3">
                {prioritizedRecommendations.length > 0 ? (
                  prioritizedRecommendations.map((item, index) => (
                    <li
                      key={`${item.text}-${index}`}
                      className="rounded-md border border-(--line) bg-(--line-2) p-3"
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-(--t-1)">
                          {index + 1}. {item.text}
                        </p>
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${item.priority === "High" ? "bg-rose-500/20 text-rose-200" : "bg-sky-500/20 text-sky-200"}`}
                        >
                          {item.priority}
                        </span>
                      </div>
                      <p className="text-xs text-(--t-2)">{item.reason}</p>
                    </li>
                  ))
                ) : (
                  <li className="rounded-md border border-(--line) bg-(--line-2) p-3 text-sm text-(--t-2)">
                    No roadmap items were returned for this audit.
                  </li>
                )}
              </ul>
            </div>
          </div>
        </section>

        {warnings.length > 0 && (
          <div className="mb-8 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-amber-100">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-amber-200">
              Warnings
            </h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
              {warnings.map((warning, index) => (
                <li key={`${warning}-${index}`}>{warning}</li>
              ))}
            </ul>
          </div>
        )}

        {hallucinationSnapshot && (
          <section className="mb-8 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-rose-100">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              <h3 className="text-sm font-semibold uppercase tracking-wider text-rose-200">
                {hallucinationSnapshot.hasCertificate
                  ? "Integrity Review Details"
                  : "Hallucination Risk Details"}
              </h3>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-md border border-rose-400/30 bg-(--line-2) p-4 text-center flex flex-col items-center justify-center">
                <p className="text-xs text-rose-200/80 mb-1">Status Overview</p>
                <p
                  className={`text-xl font-bold ${hallucinationSnapshot.flagged ? "text-rose-400" : "text-emerald-400"}`}
                >
                  {hallucinationSnapshot.flagged ? "FLAGGED" : "CLEAN"}
                </p>
              </div>
              <div className="sm:col-span-1 lg:col-span-2">
                <HallucinationGauge
                  flaggedClaims={hallucinationSnapshot.flaggedClaims}
                  totalClaims={hallucinationSnapshot.totalClaims}
                  hasCertificate={hallucinationSnapshot.hasCertificate}
                />
              </div>
              <div className="rounded-md border border-rose-400/30 bg-(--line-2) p-4">
                <p className="text-xs text-rose-200/80">Average Certainty</p>
                <p className="mt-1 text-xl font-bold text-(--t-1)">
                  {hallucinationSnapshot.averageCertainty !== null
                    ? `${Math.round(hallucinationSnapshot.averageCertainty * 100)}%`
                    : "N/A"}
                </p>
                <p className="mt-2 text-[10px] text-rose-100/70">
                  Mean certainty across all grounded claims evaluated in this report.
                </p>
              </div>
              <div className="rounded-md border border-rose-400/30 bg-(--line-2) p-4">
                <p className="text-xs text-rose-200/80">Claims Omitted</p>
                <p className="mt-1 text-xl font-bold text-(--t-1)">
                  {hallucinationSnapshot.omittedClaims}
                </p>
                <p className="mt-2 text-[10px] text-rose-100/70">
                  {hallucinationSnapshot.hasCertificate
                    ? "Claims omitted from factual output or blocked during prescriptive integrity review."
                    : "Low-certainty narrative or recommendation claims removed before packaging."}
                </p>
              </div>
            </div>

            {hallucinationSnapshot.hasCertificate && (
              <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-md border border-rose-400/30 bg-(--line-2) p-4">
                  <p className="text-xs text-rose-200/80">Grounding Profile</p>
                  <p className="mt-1 text-xl font-bold text-(--t-1)">
                    {hallucinationSnapshot.groundingProfileLabel ?? "Legacy review"}
                  </p>
                  <p className="mt-2 text-[10px] text-rose-100/70">
                    {hallucinationSnapshot.dualTrackGroundingEnabled
                      ? "Track A and Track B were summarized independently."
                      : "Single-track grounding remains the active authority."}
                  </p>
                </div>
                <div className="rounded-md border border-rose-400/30 bg-(--line-2) p-4">
                  <p className="text-xs text-rose-200/80">Track A</p>
                  <p className="mt-1 text-xl font-bold text-(--t-1)">
                    {hallucinationSnapshot.trackASupported}/{hallucinationSnapshot.trackATotal}
                  </p>
                  <p className="mt-2 text-[10px] text-rose-100/70">
                    Supported factual claims. {hallucinationSnapshot.trackAFlagged} flagged and{" "}
                    {hallucinationSnapshot.trackAOmitted} omitted.
                  </p>
                </div>
                <div className="rounded-md border border-rose-400/30 bg-(--line-2) p-4">
                  <p className="text-xs text-rose-200/80">Track B</p>
                  <p className="mt-1 text-xl font-bold text-(--t-1)">
                    {hallucinationSnapshot.trackBTotal > 0
                      ? `${hallucinationSnapshot.trackBPassed}/${hallucinationSnapshot.trackBTotal}`
                      : "N/A"}
                  </p>
                  <p className="mt-2 text-[10px] text-rose-100/70">
                    {hallucinationSnapshot.trackBTotal > 0
                      ? hallucinationSnapshot.trackBNeedsManualReview > 0
                        ? `${hallucinationSnapshot.trackBBlocked} prescriptive claims were blocked, including ${hallucinationSnapshot.trackBNeedsManualReview} requiring manual verification.`
                        : `${hallucinationSnapshot.trackBBlocked} prescriptive claims were blocked.`
                      : "No prescriptive shadow claims were recorded."}
                  </p>
                </div>
                <div className="rounded-md border border-rose-400/30 bg-(--line-2) p-4">
                  <p className="text-xs text-rose-200/80">Review State</p>
                  <p className="mt-1 text-xl font-bold text-(--t-1)">
                    {hallucinationSnapshot.degraded ? "DEGRADED" : "STABLE"}
                  </p>
                  <p className="mt-2 text-[10px] text-rose-100/70">
                    {hallucinationSnapshot.degraded
                      ? (formatIntegrityLabel(hallucinationSnapshot.degradedReason) ??
                        "Part of the integrity review used a safe fallback.")
                      : "Client-safe output omits internal rewrite suggestions."}
                  </p>
                </div>
              </div>
            )}

            {hallucinationSnapshot.hasCertificate &&
              hallucinationSnapshot.blockedBuckets.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-rose-200">
                    Blocked Claim Buckets
                  </p>
                  <ul className="mt-2 space-y-2 text-sm">
                    {hallucinationSnapshot.blockedBuckets.map((bucket) => (
                      <li
                        key={bucket.key}
                        className="rounded-md border border-rose-400/30 bg-(--line-2) p-3"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="font-medium text-(--t-1)">
                            {bucket.trackLabel}: {bucket.categoryLabel}
                          </p>
                          <span className="rounded-full border border-rose-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-rose-200">
                            {bucket.count}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

            {hallucinationSnapshot.hasCertificate && trackBReviewClaims.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-rose-200">
                  Prescriptive Claim Review
                </p>
                <ul className="mt-2 space-y-2 text-sm">
                  {trackBReviewClaims.map((claim) => (
                    <li
                      key={claim.key}
                      className="rounded-md border border-rose-400/30 bg-(--line-2) p-3"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="font-medium text-(--t-1)">{claim.claimText}</p>
                        <div className="flex flex-wrap gap-2">
                          <span
                            className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${trackBDispositionTone(claim.shadowDisposition)}`}
                          >
                            {formatTrackBDispositionLabel(claim.shadowDisposition)}
                          </span>
                          {claim.confidenceBand ? (
                            <span
                              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${certaintyTone(claim.confidenceBand)}`}
                            >
                              {formatIntegrityLabel(claim.confidenceBand) ?? claim.confidenceBand}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <p className="mt-2 text-xs text-rose-100/80">
                        {claim.judgeResolution ??
                          "The judge could not approve this prescriptive claim without human review."}
                      </p>
                      {claim.reasonCodes.length > 0 && (
                        <p className="mt-2 text-[10px] text-rose-100/70">
                          Signals:{" "}
                          {claim.reasonCodes
                            .map((code) => formatIntegrityLabel(code) ?? code)
                            .join(", ")}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {hallucinationSnapshot.unsupportedSentences.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-rose-200">
                  Flagged Low-certainty Claims
                </p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                  {hallucinationSnapshot.unsupportedSentences.map((sentence, index) => (
                    <li key={`${sentence}-${index}`}>{sentence}</li>
                  ))}
                </ul>
              </div>
            )}

            {hallucinationSnapshot.fieldSummaries.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-rose-200">
                  Field-level Certainty
                </p>
                <ul className="mt-2 space-y-2 text-sm">
                  {hallucinationSnapshot.fieldSummaries.map((summary) => (
                    <li
                      key={summary.field_path}
                      className="rounded-md border border-rose-400/30 bg-(--line-2) p-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-medium text-(--t-1)">{summary.label}</p>
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${certaintyTone(summary.certainty_level)}`}
                        >
                          {summary.certainty_level}
                        </span>
                      </div>
                      <p className="mt-2 text-xs text-rose-100/80">
                        {summary.supported_claims} supported · {summary.flagged_claims} flagged ·{" "}
                        {summary.omitted_claims} omitted
                      </p>
                      <p className="mt-1 text-[10px] text-rose-100/70">
                        Average certainty {Math.round(summary.average_certainty * 100)}%
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {hallucinationSnapshot.highRiskDiscrepancies.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-rose-200">
                  High-risk Discrepancies
                </p>
                <ul className="mt-2 space-y-2 text-sm">
                  {hallucinationSnapshot.highRiskDiscrepancies.map((claim, index) => (
                    <li
                      key={`${claim.claim_text ?? "claim"}-${index}`}
                      className="rounded-md border border-rose-400/30 bg-(--line-2) p-3"
                    >
                      <p className="text-(--t-1)">{claim.claim_text ?? "Claim text unavailable"}</p>
                      {claim.field_label && (
                        <p className="mt-1 text-xs text-rose-100/80">Field: {claim.field_label}</p>
                      )}
                      <p className="mt-1 text-xs text-rose-100/80">
                        Severity: {claim.severity ?? "unknown"} · Type:{" "}
                        {claim.discrepancy_type ?? "general_mismatch"} · Certainty:{" "}
                        {claim.certainty_score !== undefined && claim.certainty_score !== null
                          ? `${Math.round(claim.certainty_score * 100)}%`
                          : "N/A"}
                      </p>
                      {Array.isArray(claim.evidence_refs) &&
                        claim.evidence_refs.length > 0 &&
                        claim.evidence_refs[0]?.excerpt && (
                          <p className="mt-2 text-xs text-rose-100/70">
                            Best evidence: {claim.evidence_refs[0].excerpt}
                          </p>
                        )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {report.debate?.enabled && <DebateProcessCard debate={report.debate} />}

        {screenshotUrl && (
          <div className="mb-8 rounded-xl border border-(--line) bg-surface p-4">
            <h3 className="mb-3 text-lg font-semibold text-(--t-1)">Captured Page Screenshot</h3>
            <div className="overflow-hidden rounded-lg border border-(--line)">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={screenshotUrl} alt="Captured page" className="w-full h-auto" />
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="flex flex-col items-center justify-center rounded-lg border border-(--line) bg-(--line-2) p-6 lg:col-span-1">
            <ScoreGauge score={overallScore} label="Overall AI Visibility Score" />
            <p className="text-center text-(--t-2) mt-4">
              This score represents the overall readiness of your content for AI-driven search
              engines.
            </p>
          </div>
          <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="rounded-lg border border-(--line) bg-(--line-2) p-6">
              <div className="flex items-center text-thoth-brass mb-4">
                <BrainCircuit className="w-6 h-6 mr-2" />
                <h3 className="text-xl font-semibold">AI Analysis</h3>
              </div>
              <div className="grid grid-cols-2 gap-4">
                {scoreGroups.slice(0, 2).map((group) => (
                  <ScoreGauge key={group.label} score={group.score} label={group.label} />
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-(--line) bg-(--line-2) p-6">
              <div className="flex items-center text-thoth-logic mb-4">
                <ShieldCheck className="w-6 h-6 mr-2" />
                <h3 className="text-xl font-semibold">Trust & Technicals</h3>
              </div>
              <div className="grid grid-cols-2 gap-4">
                {scoreGroups.slice(2, 4).map((group) => (
                  <ScoreGauge key={group.label} score={group.score} label={group.label} />
                ))}
              </div>
            </div>
          </div>

          <div className="mt-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div className="lg:col-span-1">
              <DetailedSignalList
                title="AI answers signals"
                signals={[
                  {
                    label: "Answerability",
                    score: report.aeo_signals?.answerability_score ?? 0,
                    description: "How well content directly answers questions",
                  },
                  {
                    label: "Voice Readiness",
                    score: report.aeo_signals?.voice_readiness_score ?? 0,
                    description: "Optimization for voice search queries",
                  },
                  {
                    label: "Schema Completeness",
                    score: report.aeo_signals?.schema_completeness ?? 0,
                    description: "Extent of structured data implementation",
                  },
                  {
                    label: "Content Freshness",
                    score: report.aeo_signals?.content_freshness_score ?? 0,
                    description: "Recency and relevance of content",
                  },
                ]}
              />
            </div>
            <div className="lg:col-span-1">
              <DetailedSignalList
                title="AI visibility signals"
                signals={[
                  {
                    label: "Local Authority",
                    score: report.geo_signals?.local_authority_score ?? 0,
                    description: "Strength of local presence and citations",
                  },
                  {
                    label: "Citation Consistency",
                    score: report.geo_signals?.citation_consistency_score ?? 0,
                    description: "Accuracy of NAP info across directories",
                  },
                  {
                    label: "Relevance",
                    score: report.geo_signals?.relevance_score ?? 0,
                    description: "Topical alignment with local intent",
                  },
                ]}
              />
            </div>
            <div className="lg:col-span-1">
              <DetailedSignalList
                title="Technical Signals"
                signals={[
                  {
                    label: "Performance Score",
                    score: report.technical_signals?.performance?.score ?? 0,
                    description: "Google PageSpeed Performance Score",
                  },
                  {
                    label: "Network Level",
                    score: report.technical_signals?.network?.supports_http2 ? 100 : 0,
                    description: "HTTP/2+ Transport Support",
                  },
                  {
                    label: "Visual Stability",
                    score:
                      report.technical_signals?.performance?.cls !== undefined &&
                      report.technical_signals?.performance?.cls !== null
                        ? Math.max(0, 100 - report.technical_signals.performance.cls * 100)
                        : 0,
                    description: "Cumulative Layout Shift Proxy",
                  },
                ]}
              />
            </div>
          </div>
        </div>
        <div className="mt-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-6">
            <EntityChips entities={entities} />
            {entitySummary && (
              <div className="rounded-lg border border-(--line) bg-(--line-2) p-6">
                <h3 className="mb-3 text-xl font-semibold text-(--t-1)">Entity Summary</h3>
                <p className="text-(--t-2) text-sm leading-relaxed">{entitySummary}</p>
              </div>
            )}
            <RecommendationsList recommendations={recommendations} siteUrl={reportUrl} />
          </div>
          <div className="lg:col-span-1 space-y-6">
            <TechnicalMetrics metrics={performanceMetrics} />
            <div className="rounded-lg border border-(--line) bg-(--line-2) p-6">
              <div className="mb-4 flex items-center text-thoth-brass">
                <Globe className="w-6 h-6 mr-2" />
                <h3 className="text-xl font-semibold">Network Analysis</h3>
              </div>
              <div className="space-y-3 text-sm text-(--t-2)">
                <div className="flex items-center justify-between">
                  <span>HTTP Version</span>
                  <span className="text-(--t-1) font-semibold">
                    {networkAnalysis?.http_version ?? "Unknown"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>HTTP/2 Support</span>
                  <span className="text-(--t-1) font-semibold">
                    {networkAnalysis?.supports_http2 ? "Yes" : "No"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>HTTP/3 Advertised</span>
                  <span className="text-(--t-1) font-semibold">
                    {networkAnalysis?.supports_http3_inferred ? "Yes" : "No"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default AuditReport;
