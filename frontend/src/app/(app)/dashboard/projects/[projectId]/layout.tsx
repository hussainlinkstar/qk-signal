"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/**
 * Project-scoped layout. Navigation, the project switcher, credits and branding
 * are all owned by the workspace shell (SignalAppShell in DashboardLayoutClient),
 * matching the signal-MVP design where a project page is just the sidebar + the
 * page content. This layout therefore only scrolls to top on route changes and
 * renders the active page — no extra "snapshot / modules / execution lanes"
 * chrome (that was the old three-pillar dashboard and is intentionally removed).
 */
export default function ProjectDashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [pathname]);

  return <div className="min-w-0 w-full">{children}</div>;
}
