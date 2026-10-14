"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getTierDurations, type TierDurationFigure } from "@/services/auditService";

/**
 * The measured per-tier scan durations, as the start-scan page needs them
 * (SIGV2-1177).
 *
 * The product states no invented runtime: the only figures a customer sees are
 * the ones derived from completed `audit_jobs` runs, served by
 * `GET /api/v1/audit/tier-durations`. That endpoint publishes the p25..p75
 * range in whole minutes per tier, and only for a tier with enough recent
 * runs behind it.
 *
 * The read happens once here, at the page level, so the depth table and the
 * Launch sentence cannot state different figures. A tier absent from the map
 * has no publishable measurement and the surface must state none: an empty
 * cell, not a borrowed number and not a zero. A failed or pending read yields
 * `null` for the same reason, and never blocks anything.
 *
 * Keys arrive already canonical (`fast`, `smart`, `deep_judgment`): the
 * backend resolves its stored tier through its own `normalize_tier` before
 * publishing, so this hook passes the map through unchanged.
 */
export type TierDurationsMap = Record<string, TierDurationFigure>;

export type TierDurationsState = {
  /** Canonical-tier-keyed measured figures, or null when nothing was read. */
  durations: TierDurationsMap | null;
  isLoading: boolean;
};

type UseTierDurationsParams = {
  isSignedIn: boolean;
  getAuthHeaders: () => Promise<Record<string, string>>;
};

/**
 * Render one figure for the copy surfaces: `"8-20 min"`, or `"15 min"` when
 * the quartiles round to the same whole minute (an "N to N" range would read
 * like a promise of exactness).
 */
export function formatTierDurationRange(figure: TierDurationFigure): string {
  if (figure.low_minutes === figure.high_minutes) {
    return `${figure.low_minutes} min`;
  }
  return `${figure.low_minutes}-${figure.high_minutes} min`;
}

export function useTierDurations({
  isSignedIn,
  getAuthHeaders,
}: UseTierDurationsParams): TierDurationsState {
  const [durations, setDurations] = useState<TierDurationsMap | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(isSignedIn);

  // Latest-ref keeps `load` stable when a caller passes an inline getter:
  // keying the effect on the function identity would re-run the fetch after
  // every render and `isLoading` would toggle forever.
  const getAuthHeadersRef = useRef(getAuthHeaders);
  useEffect(() => {
    getAuthHeadersRef.current = getAuthHeaders;
  }, [getAuthHeaders]);

  const load = useCallback(async () => {
    if (!isSignedIn) {
      setDurations(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const headers = await getAuthHeadersRef.current();
      const payload = await getTierDurations(headers);
      setDurations(payload.tiers ?? {});
    } catch {
      // A missing read means no figure, never a blocker and never an invented
      // number: the surfaces state nothing and the scan still launches.
      setDurations(null);
    } finally {
      setIsLoading(false);
    }
  }, [isSignedIn]);

  useEffect(() => {
    void load();
  }, [load]);

  return useMemo(() => ({ durations, isLoading }), [durations, isLoading]);
}
