"use client";

import { createContext, useContext, type ReactNode } from "react";

/**
 * signal-MVP puts the page's `.top` content inside the single 64px shared
 * bar, not in a second header under it: workspace pages register `.dom` +
 * `.meta` (WorkspacePageFrame), project drilldowns register their `.crumb`
 * plus any `.top` actions (Export, Improve settings). DashboardLayoutClient
 * renders all of it in SignalTopBar. Pages that register nothing leave the
 * bar's left side empty, the approved state for workspace sub-pages.
 */
export type WorkspacePageHeader = {
  title?: string;
  meta?: string;
  /** Approved `.top > .crumb`; replaces the `.dom` label when present. */
  crumb?: ReactNode;
  /** Approved `.top` actions after the spacer (Export, Improve settings). */
  actions?: ReactNode;
} | null;

type WorkspacePageHeaderContextValue = {
  header: WorkspacePageHeader;
  setHeader: (header: WorkspacePageHeader) => void;
};

export const WorkspacePageHeaderContext = createContext<WorkspacePageHeaderContextValue>({
  header: null,
  setHeader: () => {},
});

export function useWorkspacePageHeader(): WorkspacePageHeaderContextValue {
  return useContext(WorkspacePageHeaderContext);
}
