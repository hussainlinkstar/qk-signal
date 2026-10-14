"use client";

import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ShieldAlert,
  Eye,
  ChevronDown,
  ChevronRight,
  Filter,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { cx } from "@/components/ui/utils";
import { TIER_DISPLAY } from "@/constants/tiers";
import { REPORT_BLOCK, REPORT_BLOCK_DIVIDED, REPORT_WELL } from "./reportBlock";

type HallucinationClaim = {
  claim_id: string;
  claim_text: string;
  hallucination: boolean;
  disposition: string;
  severity: string;
  certainty_score: number;
  certainty_level: string;
  field_path?: string;
  field_label?: string;
  discrepancy_type?: string;
  matched_truth_key?: string;
  truth_value?: string;
  evidence_refs?: Array<{
    source_type?: string;
    source_key?: string;
    excerpt?: string;
    retrieval_score?: number;
  }>;
  suggested_rewrite?: string | null;
  track?: string;
  claim_kind?: string;
};

type HallucinationsTabProps = {
  hallucination: Record<string, any> | null | undefined;
};

type FilterMode = "all" | "flagged" | "supported";

// SIGV2-1317: the product's tones, and contrast that holds.
//
// Every value here used to be a Tailwind dark-theme tint on the white
// `--panel` fill. Measured against #FFFFFF: `emerald-400` 1.92:1,
// `amber-400` 1.67:1, `red-400` 2.77:1, and `emerald-200` 1.28:1. WCAG AA
// body text needs 4.5:1, so this was not low contrast, it was text a reader
// had to guess at.
//
// The approved tokens do not pass for body text either, which is the part
// worth knowing: `--good` is 3.37:1, `--warn` 2.58:1, `--bad` 3.91:1. So this
// follows what `SignalAlert` already does. The tone carries the **glyph and
// the rule**; the words sit on `--t-1` or `--t-2`, which is 6.52:1. Colour
// signals, grey is read, and the glyph means a failure is never told apart
// from a confirmation by colour alone.
const SEVERITY_CONFIG: Record<string, { tone: string; tint: string; edge: string }> = {
  high: {
    tone: "text-(--bad)",
    tint: "bg-[color-mix(in_srgb,var(--bad)_7%,transparent)]",
    edge: "border-[color-mix(in_srgb,var(--bad)_28%,transparent)]",
  },
  medium: {
    tone: "text-(--warn)",
    tint: "bg-[color-mix(in_srgb,var(--warn)_8%,transparent)]",
    edge: "border-[color-mix(in_srgb,var(--warn)_30%,transparent)]",
  },
  low: { tone: "text-(--t-2)", tint: "bg-(--line-2)", edge: "border-(--line)" },
  none: {
    tone: "text-(--good)",
    tint: "bg-[color-mix(in_srgb,var(--good)_7%,transparent)]",
    edge: "border-[color-mix(in_srgb,var(--good)_28%,transparent)]",
  },
};

/** Strip markdown link syntax, headings, images, bold, and stray formatting from raw crawled text. */
function stripMarkdown(text: string): string {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "") // full images ![alt](url)
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // full links [label](url) → keep label
    .replace(/\]\(https?:\/\/[^)]*\)/g, "") // orphaned ](url) from chunk-truncated links
    .replace(/\(https?:\/\/[^)]*\)/g, "") // bare (url) in parentheses
    .replace(/https?:\/\/\S+/g, "") // any remaining bare URLs
    .replace(/#{1,6}\s+/g, "") // headings (also mid-line, not just line-start)
    .replace(/!\[[^\]]*\]/g, "") // orphaned image alt text ![alt]
    .replace(/\[([^\]]*)\]/g, "$1") // orphaned [text] brackets → keep text
    .replace(/[\[\]]/g, "") // stray unmatched brackets left over from truncation
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, "$1") // bold/italic
    .replace(/`([^`]+)`/g, "$1") // inline code
    .replace(/\s*\* \* \*\s*/g, " ") // horizontal rules
    .replace(/^[\s*-]+$/gm, "") // lines that are only bullets/dashes/spaces
    .replace(/\n{2,}/g, "\n") // collapse blank lines
    .replace(/\s{2,}/g, " ") // collapse whitespace
    .trim();
}

// SIGV2-1317: says where a passage came from in the reader's words.
// "Source Passage #3" and "Brand Fact" are our names for our own data.
function humanizeSourceKey(key: string | undefined, t: TFunction): string {
  if (!key) return t("signalAuditReport.accuracy.sourcePassage");
  if (key.startsWith("brand_truth")) return t("signalAuditReport.accuracy.brandFact");
  const chunkMatch = key.match(/^chunk[_-]?(\d+)$/i);
  if (chunkMatch) {
    return t("signalAuditReport.accuracy.sourcePassageNumbered", { number: chunkMatch[1] });
  }
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** The i18n key and tone for how closely a passage matched (SIGV2-1317). */
function relevanceBand(score: number): { key: string; tone: string } {
  if (score >= 0.7) return { key: "relevanceStrong", tone: "text-(--good)" };
  if (score >= 0.4) return { key: "relevanceModerate", tone: "text-(--warn)" };
  return { key: "relevanceWeak", tone: "text-(--bad)" };
}

// The four approved `.alert` glyphs are distinct shapes, not four colours, so
// the outcome survives a reader who cannot separate red from green.
const DISPOSITION_CONFIG: Record<string, { icon: React.ReactNode; key: string; tone: string }> = {
  supported: {
    icon: <CheckCircle2 className="h-4 w-4 text-(--good)" aria-hidden="true" />,
    key: "supported",
    tone: "text-(--t-1)",
  },
  flagged: {
    icon: <AlertTriangle className="h-4 w-4 text-(--warn)" aria-hidden="true" />,
    key: "flagged",
    tone: "text-(--t-1)",
  },
  omitted: {
    icon: <ShieldAlert className="h-4 w-4 text-(--bad)" aria-hidden="true" />,
    key: "omitted",
    tone: "text-(--t-1)",
  },
};

function ClaimCard({ claim }: { claim: HallucinationClaim }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const severityStyle = SEVERITY_CONFIG[claim.severity] ?? SEVERITY_CONFIG.none;
  const dispositionInfo: { icon: React.ReactNode; key: string; tone: string } = DISPOSITION_CONFIG[
    claim.disposition
  ] ?? {
    icon: <Eye className="h-4 w-4 text-(--t-2)" aria-hidden="true" />,
    // An unrecognised disposition says so, rather than printing the raw
    // value from the payload at the reader.
    key: "severityLow",
    tone: "text-(--t-2)",
  };

  const hasEvidence = claim.evidence_refs && claim.evidence_refs.length > 0;
  const hasDetails = hasEvidence || claim.truth_value || claim.suggested_rewrite;

  return (
    <div
      className={cx(
        "rounded border transition-all duration-200",
        claim.hallucination
          ? "border-[color-mix(in_srgb,var(--warn)_30%,transparent)]"
          : "border-(--line) hover:bg-(--line-2)"
      )}
    >
      <button
        type="button"
        onClick={() => hasDetails && setExpanded(!expanded)}
        className="w-full text-left p-5 flex items-start gap-4"
        disabled={!hasDetails}
      >
        <div className="mt-0.5 shrink-0">{dispositionInfo.icon}</div>

        <div className="flex-1 min-w-0 space-y-2">
          <p className="text-sm text-(--t-1) leading-relaxed">{claim.claim_text}</p>

          <div className="flex flex-wrap items-center gap-3">
            {/* SIGV2-1317: the severity reads as words, not as a raw enum.
                This printed `claim.severity` straight out, so a customer met
                "high", "medium" or "none" in shouting capitals inside a pill
                whose text failed contrast. */}
            <span
              className={cx(
                "rounded-full border px-2 py-0.5 font-mono text-[10.5px] tracking-[0.06em]",
                severityStyle.tone,
                severityStyle.tint,
                severityStyle.edge
              )}
            >
              {t(
                `signalAuditReport.accuracy.severity${
                  claim.severity
                    ? claim.severity.charAt(0).toUpperCase() + claim.severity.slice(1)
                    : "Low"
                }`
              )}
            </span>

            <span className="flex items-center gap-1.5 text-[12px] text-(--t-1)">
              {dispositionInfo.icon}
              {t(`signalAuditReport.accuracy.${dispositionInfo.key}`)}
            </span>

            {claim.certainty_score > 0 && (
              <span className="font-mono text-[11px] text-(--t-2)">
                {t("signalAuditReport.accuracy.certainty")}{" "}
                {Math.round(claim.certainty_score * 100)}%
              </span>
            )}

            {claim.field_label && (
              <span className="text-[10px] text-(--t-3) tracking-wide">{claim.field_label}</span>
            )}

            {claim.track && (
              <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                {claim.track.replace("_", " ")}
              </span>
            )}
          </div>
        </div>

        {hasDetails && (
          <div className="mt-1 shrink-0 text-(--t-3)">
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </div>
        )}
      </button>

      {expanded && hasDetails && (
        <div className="border-t border-(--line) px-5 pb-5 pt-4 space-y-4">
          {claim.truth_value &&
            claim.matched_truth_key !== "no_evidence" &&
            claim.truth_value !== claim.evidence_refs?.[0]?.excerpt && (
              <div className="rounded bg-black/30 p-4 space-y-1">
                <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                  Closest Source Match
                </p>
                <p className="text-xs text-(--t-2) leading-relaxed line-clamp-4">
                  {stripMarkdown(claim.truth_value)}
                </p>
              </div>
            )}

          {hasEvidence && (
            <div className="space-y-2">
              <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                Source Evidence
              </p>
              {claim.evidence_refs!.slice(0, 3).map((ref, idx) => {
                const band =
                  typeof ref.retrieval_score === "number"
                    ? relevanceBand(ref.retrieval_score)
                    : null;
                return (
                  <div
                    key={idx}
                    className="rounded bg-(--line-2) border border-(--line) p-3 space-y-1"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        {humanizeSourceKey(ref.source_key, t)}
                      </span>
                      {band && (
                        <span className={cx("font-mono text-[11px]", band.tone)}>
                          {t(`signalAuditReport.accuracy.${band.key}`)} (
                          {Math.round(ref.retrieval_score! * 100)}%)
                        </span>
                      )}
                    </div>
                    {ref.excerpt && (
                      <p className="text-[11px] text-(--t-2) leading-relaxed line-clamp-3">
                        {stripMarkdown(ref.excerpt)}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {claim.suggested_rewrite && (
            <div className={cx(REPORT_WELL, "space-y-1")}>
              <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                Suggested Rewrite
              </p>
              {/* SIGV2-1317: `emerald-200` measured 1.28:1 on the white
                  panel, which is the single worst value on the page: a
                  suggested rewrite the reader could not read. */}
              <p className="text-[12.5px] leading-[1.55] text-(--t-1)">{claim.suggested_rewrite}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function HallucinationsTab({ hallucination }: HallucinationsTabProps) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<FilterMode>("all");

  const claims = useMemo<HallucinationClaim[]>(() => {
    if (!hallucination || !Array.isArray(hallucination.claims)) return [];
    return hallucination.claims;
  }, [hallucination]);

  const totalClaims = hallucination?.total_claims ?? claims.length;
  const flaggedCount =
    hallucination?.flagged_claims ?? claims.filter((c) => c.hallucination).length;
  const omittedCount =
    hallucination?.omitted_claims ?? claims.filter((c) => c.disposition === "omitted").length;
  const supportedCount = totalClaims - flaggedCount;
  const avgCertainty = hallucination?.average_certainty;

  const filteredClaims = useMemo(() => {
    if (filter === "flagged") return claims.filter((c) => c.hallucination);
    if (filter === "supported") return claims.filter((c) => !c.hallucination);
    return claims;
  }, [claims, filter]);

  if (!hallucination || totalClaims === 0) {
    // SIGV2-1317: two sentences, in the reader's words. This was a 64px
    // circle, an icon, "No Hallucination Data" in shouting capitals, and
    // "Claim-level integrity analysis is generated for ... tier audits",
    // which is our vocabulary rather than a customer's.
    return (
      <div className={REPORT_BLOCK}>
        <p className="m-0 max-w-prose text-[13px] leading-[1.55] text-(--t-2)">
          {t("signalAuditReport.accuracy.empty")}{" "}
          {t("signalAuditReport.accuracy.emptyDetail", { tier: TIER_DISPLAY.deep_judgment })}
        </p>
      </div>
    );
  }

  return (
    <div className={REPORT_BLOCK}>
      {/* SIGV2-1317: one row of figures, not four cards.
          Each count used to be its own bordered panel inside the section's
          own card, with the number itself painted in a failing colour
          (`amber-400` at 1.67:1, `red-400` at 2.77:1, `emerald-400` at
          1.92:1 on white). The glyph carries the tone now and the number sits
          on `--t-1`, so the figure is legible and the meaning still reads
          without relying on colour. */}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {[
          {
            icon: <Eye className="h-3.5 w-3.5 text-(--purple)" aria-hidden="true" />,
            label: t("signalAuditReport.accuracy.totalClaims"),
            value: totalClaims,
          },
          {
            icon: <AlertTriangle className="h-3.5 w-3.5 text-(--warn)" aria-hidden="true" />,
            label: t("signalAuditReport.accuracy.countFlagged"),
            value: flaggedCount,
          },
          {
            icon: <ShieldAlert className="h-3.5 w-3.5 text-(--bad)" aria-hidden="true" />,
            label: t("signalAuditReport.accuracy.countOmitted"),
            value: omittedCount,
          },
          {
            icon: <CheckCircle2 className="h-3.5 w-3.5 text-(--good)" aria-hidden="true" />,
            label: t("signalAuditReport.accuracy.countSupported"),
            value: supportedCount,
          },
        ].map((metric) => (
          <div key={metric.label} data-accuracy-metric={metric.label}>
            <div className="flex items-center gap-2">
              {metric.icon}
              <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                {metric.label}
              </span>
            </div>
            <div className="mt-1.5 font-(family-name:--disp) text-[27px] font-black leading-none tracking-[-0.02em] text-(--t-1)">
              {metric.value}
            </div>
          </div>
        ))}
      </div>

      {/* Average certainty bar */}
      {typeof avgCertainty === "number" && (
        <div className={cx(REPORT_BLOCK_DIVIDED, "space-y-3")}>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
              Average Certainty Score
            </span>
            <span className="text-sm font-black text-(--t-1)">
              {Math.round(avgCertainty * 100)}%
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-(--line-2) overflow-hidden">
            <div
              className={cx(
                "h-full rounded-full transition-all duration-700",
                // A filled bar is a shape, not text, so the tone tokens are
                // right here: they only have to be distinguishable, and the
                // number beside the bar carries the reading.
                avgCertainty >= 0.7
                  ? "bg-(--good)"
                  : avgCertainty >= 0.4
                    ? "bg-(--warn)"
                    : "bg-(--bad)",
                "w-(--bw)"
              )}
              style={{ "--bw": `${Math.round(avgCertainty * 100)}%` } as React.CSSProperties}
            />
          </div>
        </div>
      )}

      {/* Filter bar */}
      <div className="flex items-center gap-3">
        <Filter className="w-4 h-4 text-(--t-3)" />
        {(
          [
            { key: "all", label: "All Claims", count: claims.length },
            {
              key: "flagged",
              label: "Flagged",
              count: claims.filter((c) => c.hallucination).length,
            },
            {
              key: "supported",
              label: "Supported",
              count: claims.filter((c) => !c.hallucination).length,
            },
          ] as const
        ).map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={cx(
              "rounded-full border px-3 py-1 text-[12px] transition-colors",
              filter === f.key
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-(--line) bg-(--line-2) text-(--t-3) hover:text-(--t-1) hover:bg-(--line-2)"
            )}
          >
            {f.label} ({f.count})
          </button>
        ))}
      </div>

      {/* Claims list */}
      <div className="space-y-3">
        {filteredClaims.map((claim) => (
          <ClaimCard key={claim.claim_id} claim={claim} />
        ))}
        {filteredClaims.length === 0 && (
          <div className="py-8 text-center text-[13px] text-(--t-2)">
            No claims match the current filter
          </div>
        )}
      </div>
    </div>
  );
}
