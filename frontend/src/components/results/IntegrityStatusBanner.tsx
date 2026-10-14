"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React from "react";

import AiDisclaimer from "@/components/ui/AiDisclaimer";
import { cx } from "@/components/ui/utils";
import { formatIntegrityLabel, getIntegrityStatusSnapshot } from "@/lib/integrityStatus";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";

type IntegrityStatusBannerProps = {
  report: CanonicalAuditReport;
  variant?: "compact" | "detailed";
  className?: string;
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  google_search_console: "Google Search Console",
  google_analytics_4: "Google Analytics 4",
  bing_webmaster: "Bing Webmaster Tools",
};

const formatSourceList = (labels: string[]): string => {
  if (labels.length <= 1) {
    return labels[0] ?? "";
  }

  if (labels.length === 2) {
    return `${labels[0]} and ${labels[1]}`;
  }

  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
};

const getExternalDataSummary = (
  metadata: Record<string, any> | undefined
): {
  hasExternalData: boolean;
  connectedSourceLabels: string[];
} => {
  const rawSources = Array.isArray(metadata?.data_sources?.sources)
    ? (metadata?.data_sources?.sources as Array<Record<string, unknown>>)
    : [];

  const connectedSourceLabels = Array.from(
    new Set(
      rawSources.flatMap((entry) => {
        if (!entry || typeof entry !== "object") {
          return [];
        }

        if (entry.is_active === false || entry.has_external_data !== true) {
          return [];
        }

        const sourceLabel =
          typeof entry.source_label === "string" && entry.source_label.trim()
            ? entry.source_label.trim()
            : null;
        const sourceType = typeof entry.source_type === "string" ? entry.source_type.trim() : "";
        const fallbackLabel = SOURCE_TYPE_LABELS[sourceType] ?? null;
        const resolvedLabel = sourceLabel ?? fallbackLabel;

        return resolvedLabel ? [resolvedLabel] : [];
      })
    )
  );

  const explicitHasExternalData = metadata?.has_external_data_sources === true;
  const dataSourceMode =
    typeof metadata?.data_source_mode === "string" ? metadata.data_source_mode.trim() : "";

  const hasExternalData =
    connectedSourceLabels.length > 0 ||
    (rawSources.length === 0 &&
      (explicitHasExternalData ||
        (dataSourceMode.length > 0 && dataSourceMode !== "ai_estimate_only")));

  return {
    hasExternalData,
    connectedSourceLabels,
  };
};

export default function IntegrityStatusBanner({
  report,
  variant = "compact",
  className,
}: IntegrityStatusBannerProps) {
  const snapshot = getIntegrityStatusSnapshot(report);

  if (!snapshot) {
    return null;
  }

  const isFlagged = snapshot.flagged;
  const claimPreview = snapshot.unsupportedSentences.slice(0, 3);
  const { hasExternalData, connectedSourceLabels } = getExternalDataSummary(report.metadata);
  const profileLabel = snapshot.groundingProfileLabel ?? "Standard review";
  const reviewCountLabel =
    snapshot.reviewClaimCount > 0
      ? `${snapshot.reviewClaimCount} claim${snapshot.reviewClaimCount === 1 ? "" : "s"} need review`
      : "No blocked claims recorded";
  const blockedBuckets = snapshot.blockedBuckets.slice(0, variant === "compact" ? 2 : 4);

  const summaryText = isFlagged
    ? snapshot.hasCertificate
      ? "The integrity certificate recorded flagged, omitted, or strategically blocked claims in this run. Review the track split before sharing recommendations."
      : "Automated claim screening found potentially unsupported AI-generated claims in this run. Review the generated narrative and supporting evidence before sharing."
    : snapshot.hasCertificate
      ? "The integrity certificate did not record blocked claims in this run. This remains a review signal, not a guarantee of factual accuracy."
      : "Automated claim screening did not flag unsupported AI-generated claims in this run. This is a risk signal, not a guarantee of factual accuracy.";

  const disclaimerText = hasExternalData
    ? connectedSourceLabels.length > 0
      ? `This report combines automated AI analysis with connected external data from ${formatSourceList(connectedSourceLabels)}. Verify critical decisions against the source systems before publishing or implementing changes.`
      : "This report combines automated AI analysis with connected external data. Verify critical decisions against the source systems before publishing or implementing changes."
    : null;

  return (
    <div
      className={cx(
        "rounded-(--r-md) border border-(--line) bg-(--panel)",
        variant === "compact" ? "p-4" : "p-6",
        className
      )}
    >
      <div className={cx("relative z-10", variant === "compact" ? "space-y-4" : "space-y-6")}>
        <SignalAlert tone={isFlagged ? "warning" : "success"} title="Integrity Status">
          <p className="mb-1">
            {snapshot.degraded
              ? "Degraded review fallback was used"
              : isFlagged
                ? snapshot.hasCertificate
                  ? "Claims were flagged or blocked by integrity review"
                  : "Potential unsupported claims flagged"
                : snapshot.hasCertificate
                  ? "No claims were blocked by integrity review"
                  : "No unsupported claims flagged by automated review"}
          </p>
          <p>{summaryText}</p>
        </SignalAlert>

        <div
          className={cx(
            "grid gap-3",
            variant === "compact" ? "md:grid-cols-3" : "md:grid-cols-2 xl:grid-cols-4"
          )}
        >
          <div className="rounded-xl border border-(--line) bg-(--line-2) p-3">
            <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-2)">
              Grounding Profile
            </p>
            <p className="mt-2 text-sm font-semibold text-(--t-1)">{profileLabel}</p>
            <p className="mt-1 text-[11px] text-(--t-2)">
              {snapshot.dualTrackGroundingEnabled
                ? "Track A and Track B were evaluated independently."
                : "Standard single-track claim review was applied."}
            </p>
          </div>

          <div className="rounded-xl border border-(--line) bg-(--line-2) p-3">
            <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-2)">Track A</p>
            <p className="mt-2 text-sm font-semibold text-(--t-1)">
              {snapshot.trackASupported}/{snapshot.trackATotal} supported
            </p>
            <p className="mt-1 text-[11px] text-(--t-2)">
              {snapshot.trackAFlagged} flagged · {snapshot.trackAOmitted} omitted
            </p>
          </div>

          <div className="rounded-xl border border-(--line) bg-(--line-2) p-3">
            <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-2)">Track B</p>
            <p className="mt-2 text-sm font-semibold text-(--t-1)">
              {snapshot.trackBTotal > 0
                ? `${snapshot.trackBPassed}/${snapshot.trackBTotal} passed`
                : "Not engaged"}
            </p>
            <p className="mt-1 text-[11px] text-(--t-2)">
              {snapshot.trackBTotal > 0
                ? `${snapshot.trackBBlocked} blocked during prescriptive review`
                : "Track B was not active for this audit."}
            </p>
          </div>

          <div className="rounded-xl border border-(--line) bg-(--line-2) p-3">
            <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-2)">
              Review State
            </p>
            <p className="mt-2 text-sm font-semibold text-(--t-1)">{reviewCountLabel}</p>
            <p className="mt-1 text-[11px] text-(--t-2)">
              {snapshot.degraded
                ? (formatIntegrityLabel(snapshot.degradedReason) ?? "Review degraded")
                : "Internal rewrite details are excluded from this summary."}
            </p>
          </div>
        </div>

        {disclaimerText && (
          <AiDisclaimer
            text={disclaimerText}
            className="border-(--line) bg-(--line-2) [&>p]:text-(--t-2) [&>svg]:text-(--t-2)"
          />
        )}

        {snapshot.hasCertificate && blockedBuckets.length > 0 && (
          <div className="grid gap-3">
            <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-2)">
              Blocked Claim Buckets
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              {blockedBuckets.map((bucket) => (
                <div
                  key={bucket.key}
                  className="rounded-xl border border-(--line) bg-black/30 p-4 text-xs text-(--t-1)"
                >
                  <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-3)">
                    {bucket.trackLabel}
                  </p>
                  <p className="mt-2 text-sm font-semibold text-(--t-1)">{bucket.categoryLabel}</p>
                  <p className="mt-1 text-[11px] text-(--t-2)">
                    {bucket.count} blocked claim{bucket.count === 1 ? "" : "s"}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {snapshot.degraded && (
          <SignalAlert tone="warning" title="Degraded review">
            {formatIntegrityLabel(snapshot.degradedReason) ??
              "Part of the integrity review fell back to a safe mode."}
          </SignalAlert>
        )}

        {variant === "detailed" && isFlagged && claimPreview.length > 0 && (
          <div className="grid gap-3">
            {claimPreview.map((claimText, index) => (
              <div
                key={`${claimText}-${index}`}
                className="rounded-xl border border-amber-500/10 bg-(--line-2) p-4 text-xs text-amber-100/80 shadow-inner transition-colors hover:bg-black/60"
              >
                <span className="mr-2 text-amber-500/50">FLAGGED:</span>
                &quot;{claimText}&quot;
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
