"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchVisibilityQueries } from "@/services/monitoringService";
import { fetchProjectById } from "@/services/workspaceService";
import type { ProjectDetails } from "@/services/workspaceService";
import type {
  SearchTypeCoverageEntry,
  VisibilityEntitlements,
  VisibilityQuery,
} from "@/types/monitoring";

/**
 * The project's prompt list, as the start-scan page needs it (SIGV2-1176).
 *
 * Jake's design puts prompts into scan setup: the section reads the project's
 * own prompt list rather than keeping a scan-local copy, and at least one
 * prompt is required before a scan can start. That rule is what stops a scan
 * producing a project whose AIO search types, Prompts tab, five "Why AI
 * recommends / ignores your website" cards, four AI visibility rows and
 * "Does AI find you?" are all empty.
 *
 * The active prompts are what matter here: they are the set the visibility
 * worker measures and the set the plan cap counts, so `include_inactive` is
 * false.
 *
 * Three states have to be distinguished, because only one of them may stop a
 * customer scanning:
 *
 * - **satisfied**: the project has at least one prompt, so nothing is blocked.
 * - **missing**: the project has none and the plan allows adding one. This is
 *   the only state that blocks the launch, and the section says so and offers
 *   the control that resolves it.
 * - **unknown**: there is no project yet (the workspace-level start-scan form
 *   finds or creates one when the run starts, so there is no prompt list to
 *   read and nothing to attach a prompt to), the read failed, or the plan
 *   permits no prompts at all. None of these may block a scan: a customer
 *   must never be unable to scan because of a requirement they have no way to
 *   meet, or because an unrelated endpoint was briefly unreachable.
 */
export type ScanPromptsState = {
  /** The project whose list this is, or null when the scan has no project. */
  projectId: number | null;
  prompts: VisibilityQuery[];
  /**
   * Per-search-type coverage served with the same response (SIGV2-1186): which
   * of the five scored types no active prompt maps to. The setup surface says
   * so before the launch rather than letting a type come back unmeasured.
   */
  coverage: SearchTypeCoverageEntry[];
  /** Served plan allowance. Never a client-side copy of the plan ladder. */
  entitlements: VisibilityEntitlements | null;
  /**
   * The project itself (SIGV2-1194): the prompt-setup surface shows the
   * starter set as derived from these details. Null while unread or when the
   * project read failed, which never fails the prompt list alongside it.
   */
  project: ProjectDetails | null;
  isLoading: boolean;
  error: string | null;
  /** The plan has room for another prompt (and permits them at all). */
  canAddPrompt: boolean;
  /** The plan permits no prompts whatsoever, so the rule cannot apply. */
  isPlanLocked: boolean;
  /** At least one prompt exists, so the mandatory-prompt rule is met. */
  hasPrompt: boolean;
  /** The launch must be refused until a prompt exists. */
  blocksLaunch: boolean;
  reload: () => Promise<void>;
};

type UseScanPromptsParams = {
  projectId?: number;
  isSignedIn: boolean;
  getAuthHeaders: () => Promise<Record<string, string>>;
};

export function useScanPrompts({
  projectId,
  isSignedIn,
  getAuthHeaders,
}: UseScanPromptsParams): ScanPromptsState {
  const incomingProjectId = typeof projectId === "number" && projectId > 0 ? projectId : null;

  // SIGV2-1287: the resolved project outlives a URL that stops naming it.
  //
  // The scan form derives its project from the `projectId` query parameter and
  // nothing else, so any navigation that did not carry it forward turned this
  // to null. The prompt list then emptied and the panel announced "this scan
  // has no project yet" to someone who had a project with prompts in it,
  // indistinguishable from having lost their work.
  //
  // Remembering the last project we were given keeps the form configuring the
  // project it was opened for. A different project id replaces it, because
  // that is a deliberate change of subject rather than a lost parameter.
  const [stickyProjectId, setStickyProjectId] = useState<number | null>(incomingProjectId);
  useEffect(() => {
    if (incomingProjectId !== null) setStickyProjectId(incomingProjectId);
  }, [incomingProjectId]);
  const resolvedProjectId = incomingProjectId ?? stickyProjectId;
  const [prompts, setPrompts] = useState<VisibilityQuery[]>([]);
  const [coverage, setCoverage] = useState<SearchTypeCoverageEntry[]>([]);
  const [entitlements, setEntitlements] = useState<VisibilityEntitlements | null>(null);
  const [project, setProject] = useState<ProjectDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A project whose list has not been read yet is loading, not empty: an
  // "add a prompt first" refusal must never be shown on no evidence.
  const [isLoading, setIsLoading] = useState<boolean>(resolvedProjectId !== null);

  const load = useCallback(async () => {
    if (resolvedProjectId === null || !isSignedIn) {
      setPrompts([]);
      setCoverage([]);
      setEntitlements(null);
      setProject(null);
      setError(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const payload = await fetchVisibilityQueries(resolvedProjectId, headers, false);
      setPrompts(payload.queries ?? []);
      setCoverage(payload.coverage ?? []);
      setEntitlements(payload.entitlements ?? null);
      // The project read is best-effort for the context line; its failure
      // must not take the prompt list down with it.
      try {
        setProject(await fetchProjectById(resolvedProjectId, headers));
      } catch {
        setProject(null);
      }
    } catch (loadError) {
      setPrompts([]);
      setCoverage([]);
      setEntitlements(null);
      setProject(null);
      setError(
        loadError instanceof Error && loadError.message
          ? loadError.message
          : "Failed to load visibility queries."
      );
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn, resolvedProjectId]);

  useEffect(() => {
    void load();
  }, [load]);

  return useMemo(() => {
    const isPlanLocked =
      entitlements !== null &&
      (entitlements.is_locked === true ||
        (typeof entitlements.max_queries === "number" && entitlements.max_queries <= 0));
    const remaining =
      typeof entitlements?.remaining_queries === "number" ? entitlements.remaining_queries : null;
    const hasPrompt = prompts.length > 0;
    return {
      projectId: resolvedProjectId,
      prompts,
      coverage,
      entitlements,
      project,
      isLoading,
      error,
      canAddPrompt: !isPlanLocked && (remaining === null || remaining > 0),
      isPlanLocked,
      hasPrompt,
      // Known project, read succeeded, no prompts, and the plan does allow
      // one: the only case where the customer can act on the refusal.
      blocksLaunch:
        resolvedProjectId !== null &&
        error === null &&
        !isPlanLocked &&
        (isLoading || (isSignedIn && !hasPrompt)),
      reload: load,
    };
  }, [
    coverage,
    entitlements,
    error,
    isLoading,
    isSignedIn,
    load,
    project,
    prompts,
    resolvedProjectId,
  ]);
}
