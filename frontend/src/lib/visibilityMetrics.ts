import type { VisibilitySummaryResponse } from "@/types/monitoring";

export type WiredMetricKey =
  | "answerPresence"
  | "sourceCitations"
  | "engineCoverage"
  | "brandMentions";

export type DerivedMetric = {
  /** Mock `.mv` text, e.g. "3/4". */
  value: string;
  /** 0-100 fill for `.mbar` and the status chip. */
  pct: number;
};

/**
 * Derive the four metrics the overview can honestly show from
 * `GET /projects/{id}/monitoring/visibility-summary`:
 *
 * - answerPresence: per-cell `queries[].results[].presence.state` in
 *   {domain_citation, brand_mention} (the brand appeared in the answer),
 *   over `completed_checks`.
 * - sourceCitations: `cited_checks` (presence.state == domain_citation)
 *   over `completed_checks`.
 * - engineCoverage: providers in `provider_breakdown` where at least one
 *   completed cell shows the brand, over providers with completed checks.
 * - brandMentions: cells whose presence.state is exactly brand_mention, the
 *   answers that named the brand without citing the site, over
 *   `completed_checks`.
 *
 * Returns null per metric when the payload cannot support it: a locked
 * entitlement (plan gate) or zero completed checks (nothing measured yet).
 * `presence` is optional per cell, and a cell without it only reports whether
 * it was cited, which cannot separate a citation from a bare mention. Such a
 * payload leaves brandMentions null: a 0 would assert we looked and found
 * none (SIGV2-1104).
 *
 * This lives outside the panels because two surfaces render the same
 * measurement: the VISIBILITY rows in `AiVisibilityReputation` and the
 * "Appearance in AI answers" stat on the AIO card in `VisibilityPanels`
 * (SIGV2-1111). A second implementation of the same ratio is how the two
 * drift apart.
 */
export function deriveWiredMetrics(
  summary: VisibilitySummaryResponse
): Record<WiredMetricKey, DerivedMetric | null> {
  const empty: Record<WiredMetricKey, DerivedMetric | null> = {
    answerPresence: null,
    sourceCitations: null,
    engineCoverage: null,
    brandMentions: null,
  };
  if (summary.entitlements.is_locked || summary.completed_checks <= 0) return empty;

  const cells = summary.queries.flatMap((q) => q.results);
  const cellPresent = (c: (typeof cells)[number]) =>
    c.presence
      ? c.presence.state === "domain_citation" || c.presence.state === "brand_mention"
      : c.status === "cited";

  const measuredCells = cells.filter(
    (c) => c.status !== "pending" && c.presence?.state !== "unmeasured"
  );
  const present = measuredCells.filter(cellPresent).length;
  const mentionedOnly = measuredCells.filter((c) => c.presence?.state === "brand_mention").length;
  const presenceResolved =
    measuredCells.length > 0 && measuredCells.every((c) => Boolean(c.presence));

  const measuredProviders = summary.provider_breakdown.filter((p) => p.completed_checks > 0);
  const presentProviders = measuredProviders.filter((p) =>
    cells.some((c) => c.provider === p.provider && cellPresent(c))
  ).length;

  const ratio = (n: number, d: number): DerivedMetric => ({
    value: `${n}/${d}`,
    pct: d > 0 ? Math.round((n / d) * 100) : 0,
  });

  return {
    answerPresence: ratio(present, summary.completed_checks),
    sourceCitations: ratio(summary.cited_checks, summary.completed_checks),
    engineCoverage:
      measuredProviders.length > 0 ? ratio(presentProviders, measuredProviders.length) : null,
    brandMentions: presenceResolved ? ratio(mentionedOnly, summary.completed_checks) : null,
  };
}
