import React, { useState, type ReactNode } from "react";

import {
  WorkspacePageHeaderContext,
  type WorkspacePageHeader,
} from "@/components/dashboard/workspacePageHeader";

/**
 * Stands in for DashboardLayoutClient in page tests: captures what a page
 * registers through WorkspacePageHeaderContext and renders the crumb and
 * top-bar actions into the DOM, the same way SignalTopBar does in the real
 * shell, so tests can query them.
 *
 * What this costs a test, and the mistake it has caused four times (SIGV2-1146):
 * a page registers its header from an effect, so anything rendered here lands
 * one commit after the page body. When fetched data changes an action, the body
 * and the action therefore commit separately. React schedules the passive
 * effect that re-registers the action on a task, while the MutationObserver
 * that resolves `findBy*` runs on a microtask, so at the instant a row becomes
 * observable the header can still hold the previous render. Waiting on the body
 * proves nothing about the header: wait for the header state you are asserting
 * (`await waitFor(() => expect(button).toBeDisabled())`, `await findByRole(...)`)
 * or drain the queue with `await act(async () => { render(...) })`. Raising a
 * timeout only changes how often it bites.
 */
export function PageHeaderHarness({ children }: { children: ReactNode }) {
  const [header, setHeader] = useState<WorkspacePageHeader>(null);
  return (
    <WorkspacePageHeaderContext.Provider value={{ header, setHeader }}>
      {header?.crumb}
      {header?.actions}
      {children}
    </WorkspacePageHeaderContext.Provider>
  );
}
