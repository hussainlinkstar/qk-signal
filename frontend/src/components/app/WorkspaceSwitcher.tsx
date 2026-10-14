"use client";

import { useEffect, useState } from "react";

/**
 * Active-workspace state shared across the app: the localStorage key, the change
 * event, and the request header helper.
 *
 * The `WorkspaceSwitcher` UI that used to live here is gone. Workspace picking is
 * owned by `SidebarWorkspaceMenu`, the signal-MVP `.switcher`, which is the single
 * control in both the desktop sidebar foot and the mobile drawer. These helpers
 * stay because they are imported all over the dashboard.
 */
export const ACTIVE_WORKSPACE_KEY = "active_workspace_id";
export const WORKSPACE_CHANGE_EVENT = "workspace:changed";

function dispatchWorkspaceChange(workspaceId: number | null): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGE_EVENT, { detail: { workspaceId } }));
}

export function getActiveWorkspaceId(): number | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(ACTIVE_WORKSPACE_KEY);
  const parsed = raw ? parseInt(raw, 10) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

export function setActiveWorkspaceId(id: number): void {
  if (getActiveWorkspaceId() === id) return;
  localStorage.setItem(ACTIVE_WORKSPACE_KEY, String(id));
  dispatchWorkspaceChange(id);
}

export function clearActiveWorkspaceId(): void {
  if (getActiveWorkspaceId() === null) return;
  localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
  dispatchWorkspaceChange(null);
}

export function useWorkspaceVersion(): number {
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const onWorkspaceChange = () => setVersion((current) => current + 1);
    window.addEventListener(WORKSPACE_CHANGE_EVENT, onWorkspaceChange);
    return () => window.removeEventListener(WORKSPACE_CHANGE_EVENT, onWorkspaceChange);
  }, []);

  return version;
}

/** Returns extra headers to include in API requests for workspace context. */
export function workspaceHeaders(): Record<string, string> {
  const id = getActiveWorkspaceId();
  return id !== null ? { "X-Workspace-Id": String(id) } : {};
}
