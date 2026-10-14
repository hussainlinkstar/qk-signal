"use client";

import { createContext, useContext, useEffect } from "react";

/**
 * The project a route outside the `/dashboard/projects/<id>` segment is
 * currently showing (SIGV2-1180).
 *
 * The scan page carries its project in `?projectId=`, which the layout reads
 * straight from the URL. A scan's report carries no project in its URL at all:
 * the only authority for which project it belongs to is the audit record the
 * API returns, so that page registers it here and the layout keeps the
 * project's sidebar menu instead of dropping to the workspace one.
 *
 * Registering a scope is presentation only. It decides which menu is rendered;
 * it grants nothing, and every destination keeps its own workspace, plan and
 * role checks.
 */
type ProjectScopeContextValue = {
  projectId: string | null;
  setProjectId: (projectId: string | number | null) => void;
};

export const ProjectScopeContext = createContext<ProjectScopeContextValue>({
  projectId: null,
  setProjectId: () => {},
});

export function useProjectScope(): ProjectScopeContextValue {
  return useContext(ProjectScopeContext);
}

/**
 * Register the project this page is showing for as long as it is mounted.
 * Leaving the page clears the scope, so a workspace-level route never inherits
 * the previous page's project.
 */
export function useRegisterProjectScope(projectId: string | number | null | undefined): void {
  const { setProjectId } = useProjectScope();
  useEffect(() => {
    setProjectId(projectId ?? null);
    return () => setProjectId(null);
  }, [projectId, setProjectId]);
}
