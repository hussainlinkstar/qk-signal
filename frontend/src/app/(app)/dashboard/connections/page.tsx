"use client";

import ConnectionsPanels from "@/components/dashboard/settings/ConnectionsPanels";
import WorkspacePageFrame from "@/components/dashboard/WorkspacePageFrame";

// Kept as a route so existing links and OAuth callback bookmarks keep working;
// the same panels render as a section on the Workspace settings page.
export default function ConnectionsPage() {
  return (
    <WorkspacePageFrame backHref="/dashboard/settings" backLabel="Back to Workspace Settings">
      <ConnectionsPanels />
    </WorkspacePageFrame>
  );
}
