/**
 * Canonical audit tier label mapping.
 *
 * This is the **single source of truth** for user-facing audit tier names
 * used across the entire frontend.  The backend counterpart is
 * `backend/core/tier_labels.py`.
 *
 * Internal tier IDs (`fast`, `smart`, `deep_judgment`) are stable API/DB
 * values and must never change.  Only the *display* labels below are
 * user-facing.
 */

export type AuditTierId = "lite" | "fast" | "smart" | "deep_judgment";

/** Full user-facing display label (e.g. "Smart Audit"). */
export const TIER_DISPLAY: Record<AuditTierId, string> = {
  lite: "Quick Scan",
  fast: "Fast Audit",
  smart: "Smart Audit",
  deep_judgment: "Deep Analysis",
};

/** Short badge/chip label (e.g. "Smart"). */
export const TIER_SHORT: Record<AuditTierId, string> = {
  lite: "Quick",
  fast: "Fast",
  smart: "Smart",
  deep_judgment: "Deep",
};

/**
 * There is deliberately no runtime constant here. The per-tier duration the
 * product states is measured: `GET /api/v1/audit/tier-durations` serves the
 * p25..p75 range of completed runs, read once per page by
 * `useTierDurations` and shared by the depth table and the Launch sentence
 * (SIGV2-1177). A tier with no publishable measurement states none. The
 * approved-design estimates this file once held (`~5 / ~15 / ~45 min`,
 * SIGV2-1161) were never a measurement, and no figure may return here as a
 * constant.
 */

/**
 * Resolve any tier string (internal ID, uppercase, alias) to a canonical
 * `AuditTierId`.  Falls back to `"fast"`.
 */
export function normalizeTier(raw: string | null | undefined): AuditTierId {
  const cleaned = (raw ?? "").trim().toLowerCase();
  const aliases: Record<string, AuditTierId> = {
    fast: "fast",
    standard: "fast",
    lite: "lite",
    quick: "fast",
    deep: "smart",
    smart: "smart",
    thorough: "smart",
    deep_judgment: "deep_judgment",
    high_confidence: "deep_judgment",
  };
  return aliases[cleaned] ?? "fast";
}

/** Full display label (e.g. "Smart Audit"). */
export function getTierDisplay(raw: string | null | undefined): string {
  return TIER_DISPLAY[normalizeTier(raw)];
}

/** Short label (e.g. "Smart"). */
export function getTierShort(raw: string | null | undefined): string {
  return TIER_SHORT[normalizeTier(raw)];
}
