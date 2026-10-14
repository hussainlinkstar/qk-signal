import type { AuditComparisonResponse } from "@/hooks/useAuditComparison";

/**
 * "What changed" lines for a finished check.
 *
 * The approved design asks for one sentence per change. The only change data
 * this product stores for a pair of checks is the score comparison the
 * `/api/audit/{id}/comparison` endpoint returns: the four headline scores and,
 * per domain, the deterministic sub-component scores from
 * `scores.{domain}_breakdown.components` (backend `score_utils`
 * SEO_WEIGHTS / GEO_WEIGHTS / AEO_WEIGHTS plus the brand-signal blend).
 *
 * Nothing else is stored per pair of checks, so the engine-level and
 * competitor sentences in the mockup, and any count of fixes opened or closed,
 * have no source here. They are not generated.
 *
 * `CHANGE_LINE_LABEL_KEYS` is the closed set of component keys that has a
 * customer-facing name. A key outside it is skipped rather than printed as a
 * raw identifier, so a new backend component never leaks its machine name.
 */
export const CHANGE_LINE_LABEL_KEYS = [
  "core_web_vitals",
  "technical_seo",
  "onpage_content",
  "eeat_trust",
  "security_accessibility",
  "content_citability",
  "source_authority",
  "entity_clarity",
  "brand_citation",
  "llm_schema_readiness",
  "semantic_entity_density",
  "information_gain",
  "snippet_formatting",
  "brand_serp_presence",
  "brand_knowledge_graph",
  "brand_wikidata",
  "brand_ai_visibility",
] as const;

export type ChangeLineLabelKey = (typeof CHANGE_LINE_LABEL_KEYS)[number];

export type AuditChangeLine = {
  key: ChangeLineLabelKey;
  previous: number;
  current: number;
  delta: number;
};

const LABELLED = new Set<string>(CHANGE_LINE_LABEL_KEYS);

/**
 * The backend calls a movement of one point or less "stable"
 * (`audit_comparison_service._metric_direction`), so the same floor applies
 * here: anything at or below it is not reported as a change.
 */
const NOISE_FLOOR = 1;

export function deriveAuditChangeLines(
  comparison: AuditComparisonResponse | null | undefined,
  limit = 3
): AuditChangeLine[] {
  if (!comparison?.has_previous) return [];
  const subComponents = comparison.sub_components;
  if (!subComponents || typeof subComponents !== "object") return [];

  const byKey = new Map<ChangeLineLabelKey, AuditChangeLine>();

  for (const domain of Object.values(subComponents)) {
    if (!domain || typeof domain !== "object") continue;
    for (const [key, entry] of Object.entries(domain)) {
      if (!LABELLED.has(key)) continue;
      if (!entry) continue;
      const { current, previous, delta } = entry;
      if (
        typeof current !== "number" ||
        typeof previous !== "number" ||
        typeof delta !== "number" ||
        !Number.isFinite(current) ||
        !Number.isFinite(previous) ||
        !Number.isFinite(delta)
      ) {
        continue;
      }
      if (Math.abs(delta) <= NOISE_FLOOR) continue;
      const line: AuditChangeLine = {
        key: key as ChangeLineLabelKey,
        previous: Math.round(previous),
        current: Math.round(current),
        delta: Math.round(delta),
      };
      const existing = byKey.get(line.key);
      if (!existing || Math.abs(existing.delta) < Math.abs(line.delta)) {
        byKey.set(line.key, line);
      }
    }
  }

  return [...byKey.values()]
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.key.localeCompare(b.key))
    .slice(0, Math.max(0, limit));
}
