"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth/custom-auth";
import { workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import { fetchSiteTraffic } from "@/services/monitoringService";
import { fetchProjectDataSources } from "@/services/workspaceService";
import type { SiteTrafficResponse, SiteTrafficWindow } from "@/types/siteTraffic";

export interface UseSiteTrafficResult {
  traffic: SiteTrafficResponse | null;
  /**
   * Whether the workspace Google connection exists. Resolved for the two
   * states whose next step depends on it:
   * - "disconnected": account connected -> bind a property in project
   *   settings; account missing -> connect on the workspace connections page.
   * - "permission_denied" (SIGV2-1202): a workspace grant means "change
   *   Google account" is a route the customer can actually take. A binding
   *   authorized by a client magic link has no workspace grant, and sending
   *   that customer to the workspace connections page would be wrong.
   * null means not resolved (connected payload, or the lookup failed).
   */
  ga4WorkspaceConnected: boolean | null;
  /**
   * True when a GA4 binding exists (source_id set) but is switched off
   * (is_active false). The traffic read reports "disconnected" in that case,
   * which would claim nothing is connected - this flag lets the dashboard say
   * the source is paused and route to where it is switched back on.
   */
  ga4BoundInactive: boolean | null;
  loading: boolean;
  error: string | null;
  window: SiteTrafficWindow;
  setWindow: (window: SiteTrafficWindow) => void;
  refetch: () => Promise<void>;
}

/**
 * Loads GA4 site traffic for one project and period. A generation ref
 * discards stale responses (contract parity with useProjectLatestAudit):
 * switching project or window never lets an older reply overwrite a newer one.
 */
export function useSiteTraffic(projectId: string): UseSiteTrafficResult {
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();
  const [traffic, setTraffic] = useState<SiteTrafficResponse | null>(null);
  const [ga4WorkspaceConnected, setGa4WorkspaceConnected] = useState<boolean | null>(null);
  const [ga4BoundInactive, setGa4BoundInactive] = useState<boolean | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [window, setWindow] = useState<SiteTrafficWindow>("7D");
  const requestGenerationRef = useRef(0);
  // getToken is read through a ref so an unstable useAuth() return (new function
  // identity per render) cannot recreate `load` and refire the effect forever.
  const getTokenRef = useRef(getToken);
  getTokenRef.current = getToken;

  const load = useCallback(async () => {
    const generation = ++requestGenerationRef.current;
    const isCurrent = () => requestGenerationRef.current === generation;

    if (!projectId || authLoading) {
      return;
    }
    if (!isSignedIn) {
      if (!isCurrent()) return;
      setTraffic(null);
      setLoading(false);
      setError("Sign in to load site traffic.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const token = await getTokenRef.current();
      if (!token) {
        throw new Error("Authentication token unavailable.");
      }
      const headers = {
        Authorization: `Bearer ${token}`,
        ...workspaceHeaders(),
      };
      const response = await fetchSiteTraffic(projectId, window, headers);
      if (!isCurrent()) return;
      setTraffic(response);
      if (response.status === "disconnected" || response.status === "permission_denied") {
        try {
          const assignments = await fetchProjectDataSources(projectId, headers);
          if (!isCurrent()) return;
          const ga4 = assignments.find((a) => a.source_type === "google_analytics_4");
          setGa4WorkspaceConnected(ga4?.workspace_provider_connected ?? false);
          setGa4BoundInactive(Boolean(ga4?.source_id && !ga4.is_active));
        } catch {
          if (isCurrent()) {
            setGa4WorkspaceConnected(null);
            setGa4BoundInactive(null);
          }
        }
      } else {
        setGa4WorkspaceConnected(null);
        setGa4BoundInactive(null);
      }
    } catch (err) {
      if (!isCurrent()) return;
      setTraffic(null);
      setError(err instanceof Error ? err.message : "Failed to load site traffic.");
    } finally {
      if (isCurrent()) {
        setLoading(false);
      }
    }
  }, [authLoading, isSignedIn, projectId, window]);

  useEffect(() => {
    void load();
  }, [load]);

  const refetch = useCallback(async () => {
    await load();
  }, [load]);

  return {
    traffic,
    ga4WorkspaceConnected,
    ga4BoundInactive,
    loading,
    error,
    window,
    setWindow,
    refetch,
  };
}
