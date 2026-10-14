import type { CanonicalAuditReport } from "@/lib/reportAdapters";

type IntegrityFieldSummary = {
  field_path: string;
  label: string;
  total_claims: number;
  supported_claims: number;
  flagged_claims: number;
  omitted_claims: number;
  average_certainty: number;
  certainty_level: string;
};

type IntegrityHighRiskDiscrepancy = {
  claim_text?: string;
  field_label?: string;
  severity?: string;
  discrepancy_type?: string;
  certainty_level?: string;
  certainty_score?: number;
  evidence_refs?: Array<{
    excerpt?: string;
    source_key?: string;
  }>;
};

export type IntegrityBucketSummary = {
  key: string;
  track: string;
  trackLabel: string;
  category: string;
  categoryLabel: string;
  count: number;
};

export type IntegrityStatusSnapshot = {
  hasCertificate: boolean;
  flagged: boolean;
  flaggedClaims: number;
  totalClaims: number;
  omittedClaims: number;
  reviewClaimCount: number;
  averageCertainty: number | null;
  unsupportedSentences: string[];
  fieldSummaries: IntegrityFieldSummary[];
  highRiskDiscrepancies: IntegrityHighRiskDiscrepancy[];
  groundingProfile: string | null;
  groundingProfileLabel: string | null;
  dualTrackGroundingEnabled: boolean;
  trackATotal: number;
  trackASupported: number;
  trackAFlagged: number;
  trackAOmitted: number;
  trackBTotal: number;
  trackBPassed: number;
  trackBNeedsManualReview: number;
  trackBBlocked: number;
  blockedBuckets: IntegrityBucketSummary[];
  degraded: boolean;
  degradedReason: string | null;
};

const toObject = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};

const toInt = (value: unknown): number => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(0, Math.round(value));
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : 0;
  }
  return 0;
};

const toMaybeNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const toText = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

const humanizeToken = (value: string): string =>
  value
    .split("_")
    .filter(Boolean)
    .map((segment) => {
      const lower = segment.toLowerCase();
      if (lower === "a" || lower === "b" || lower === "v1") {
        return lower.toUpperCase();
      }
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");

export const formatIntegrityLabel = (value: string | null | undefined): string | null => {
  const normalized = toText(value);
  return normalized ? humanizeToken(normalized) : null;
};

export const getIntegrityStatusSnapshot = (
  report:
    | Pick<CanonicalAuditReport, "hallucination" | "integrity_certificate">
    | Record<string, unknown>
    | null
    | undefined
): IntegrityStatusSnapshot | null => {
  const payload = toObject(report);
  const hallucination = toObject(payload.hallucination);
  const integrityCertificate = toObject(payload.integrity_certificate);
  const hasCertificate = Object.keys(integrityCertificate).length > 0;
  const hasHallucination = Object.keys(hallucination).length > 0;

  if (!hasCertificate && !hasHallucination) {
    return null;
  }

  const summary = toObject(integrityCertificate.summary);
  const blockedBuckets = Array.isArray(integrityCertificate.blocked_claim_buckets)
    ? integrityCertificate.blocked_claim_buckets
        .flatMap((entry, index) => {
          const item = toObject(entry);
          const category = toText(item.category);
          const track = toText(item.track);
          const count = toInt(item.count);
          if (!category || !track || count <= 0) {
            return [];
          }
          return [
            {
              key: `${track}:${category}:${index}`,
              track,
              trackLabel: formatIntegrityLabel(track) ?? track,
              category,
              categoryLabel: formatIntegrityLabel(category) ?? category,
              count,
            },
          ];
        })
        .sort((left, right) => right.count - left.count)
    : [];

  const trackATotal = hasCertificate
    ? toInt(summary.track_a_total)
    : toInt(hallucination.total_claims);
  const trackASupported = hasCertificate
    ? toInt(summary.track_a_supported)
    : Math.max(
        0,
        trackATotal - toInt(hallucination.flagged_claims) - toInt(hallucination.omitted_claims)
      );
  const trackAFlagged = hasCertificate
    ? toInt(summary.track_a_flagged)
    : toInt(hallucination.flagged_claims);
  const trackAOmitted = hasCertificate
    ? toInt(summary.track_a_omitted)
    : toInt(hallucination.omitted_claims);
  const trackBTotal = hasCertificate ? toInt(summary.track_b_total) : 0;
  const trackBPassed = hasCertificate ? toInt(summary.track_b_supported) : 0;
  const trackBNeedsManualReview = hasCertificate ? toInt(summary.track_b_needs_manual_review) : 0;
  const trackBBlocked = hasCertificate
    ? toInt(summary.track_b_flagged) + trackBNeedsManualReview + toInt(summary.track_b_omitted)
    : 0;
  const totalClaims = hasCertificate ? toInt(summary.total_claims) : trackATotal;
  const flaggedClaims = hasCertificate ? trackAFlagged + trackBBlocked : trackAFlagged;
  const reviewClaimCount = hasCertificate
    ? trackAFlagged + trackAOmitted + trackBBlocked
    : trackAFlagged + trackAOmitted;
  const degraded = hasCertificate && integrityCertificate.degraded === true;
  const degradedReason = hasCertificate
    ? toText(integrityCertificate.degraded_reason) || null
    : null;

  const fieldSummaries = Array.isArray(hallucination.field_summaries)
    ? hallucination.field_summaries.filter(
        (item): item is IntegrityFieldSummary =>
          typeof item === "object" &&
          item !== null &&
          typeof (item as IntegrityFieldSummary).field_path === "string" &&
          typeof (item as IntegrityFieldSummary).label === "string"
      )
    : [];

  const highRiskDiscrepancies = Array.isArray(hallucination.high_risk_discrepancies)
    ? hallucination.high_risk_discrepancies.filter(
        (item): item is IntegrityHighRiskDiscrepancy => typeof item === "object" && item !== null
      )
    : [];

  const claims = Array.isArray(hallucination.claims) ? hallucination.claims : [];
  const unsupportedSentences = claims
    .filter(
      (item): item is Record<string, unknown> =>
        typeof item === "object" &&
        item !== null &&
        item.hallucination === true &&
        typeof item.claim_text === "string" &&
        item.claim_text.trim().length > 0
    )
    .map((item) => String(item.claim_text).trim());

  const averageCertainty = toMaybeNumber(hallucination.average_certainty);
  const groundingProfile = hasCertificate
    ? toText(integrityCertificate.grounding_profile) || null
    : null;
  const groundingProfileLabel = formatIntegrityLabel(groundingProfile);
  const dualTrackGroundingEnabled =
    hasCertificate && integrityCertificate.dual_track_grounding_enabled === true;
  const flagged = reviewClaimCount > 0 || hallucination.flagged === true || degraded;

  if (
    !flagged &&
    totalClaims === 0 &&
    unsupportedSentences.length === 0 &&
    fieldSummaries.length === 0 &&
    highRiskDiscrepancies.length === 0 &&
    blockedBuckets.length === 0 &&
    !groundingProfile
  ) {
    return null;
  }

  return {
    hasCertificate,
    flagged,
    flaggedClaims,
    totalClaims,
    omittedClaims: trackAOmitted,
    reviewClaimCount,
    averageCertainty,
    unsupportedSentences,
    fieldSummaries,
    highRiskDiscrepancies,
    groundingProfile,
    groundingProfileLabel,
    dualTrackGroundingEnabled,
    trackATotal,
    trackASupported,
    trackAFlagged,
    trackAOmitted,
    trackBTotal,
    trackBPassed,
    trackBNeedsManualReview,
    trackBBlocked,
    blockedBuckets,
    degraded,
    degradedReason,
  };
};
