"use client";

import { asset } from "@/lib/basePath";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import MobileDashboardDrawer from "@/components/app/MobileDashboardDrawer";

import { useAuth } from "@/components/auth/custom-auth";
import { useWorkspaceVersion, workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import type { UserSummary } from "@/types/userSummary";
import SidebarWorkspaceMenu from "@/components/app/SidebarWorkspaceMenu";
import SignalAppShell, { type SignalNavSection } from "@/components/signal/SignalAppShell";
import SignalAppFooter from "@/components/signal/SignalAppFooter";

import SignalTopBar from "@/components/signal/SignalTopBar";
import { changeAppLanguage } from "@/components/LanguageSwitcher";
import { useCookieConsent } from "@/contexts/CookieConsentContext";
import { RTL_ENABLED } from "@/lib/i18nFlags";
import { Cookie, Languages, Unplug } from "lucide-react";
import { toSignalNavSection } from "@/components/signal/mapNavSections";
import {
  adminQuickLinks,
  filterNavSectionsByMode,
  getProjectNavSections,
  normalizeProjectScopeId,
  projectWorkspaceQuickLinks,
  resolveProjectBasePath,
  workspaceNavSections,
  workspaceOverviewBackLink,
} from "@/components/navigation/navigationConfig";
import { useRoleMode } from "@/contexts/RoleModeContext";
import {
  fetchProjectById,
  fetchWorkspaceProjects,
  fetchWorkspaceWhiteLabelSettings,
  type ProjectDetails,
  type WorkspaceWhiteLabelSettings,
} from "@/services/workspaceService";
import LowScanAllowanceAlert from "@/components/billing/LowScanAllowanceAlert";
import {
  WorkspacePageHeaderContext,
  type WorkspacePageHeader,
} from "@/components/dashboard/workspacePageHeader";
import { ProjectScopeContext } from "@/components/dashboard/projectScope";
import {
  resolveDashboardDocumentTitle,
  resolveWorkspaceBrandingStyle,
  resolveWorkspaceBrandName,
} from "@/lib/workspaceBranding";

export default function DashboardLayoutClient({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const { getToken, isLoading: authLoading, isSignedIn, logout } = useAuth();
  const { roleMode } = useRoleMode();
  const workspaceVersion = useWorkspaceVersion();
  const { openSettings: openCookieSettings } = useCookieConsent();
  const [pageHeader, setPageHeader] = useState<WorkspacePageHeader>(null);
  const [registeredProjectScopeId, setRegisteredProjectScopeId] = useState<string | null>(null);

  const [userSummary, setUserSummary] = useState<UserSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [project, setProject] = useState<ProjectDetails | null>(null);
  const [branding, setBranding] = useState<WorkspaceWhiteLabelSettings | null>(null);
  const pendingSummaryRefreshRef = useRef(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}`, ...workspaceHeaders() } : workspaceHeaders();
  }, [getToken]);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me", { headers, cache: "no-store" });
      if (!response.ok) throw new Error("Unable to load account summary.");
      const payload = (await response.json()) as UserSummary;
      setUserSummary(payload);
    } catch {
      setUserSummary(null);
    } finally {
      setSummaryLoading(false);
      if (pendingSummaryRefreshRef.current) {
        pendingSummaryRefreshRef.current = false;
        void loadSummary();
      }
    }
  }, [getAuthHeaders]);

  const loadBranding = useCallback(async () => {
    try {
      const headers = await getAuthHeaders();
      const payload = await fetchWorkspaceWhiteLabelSettings(headers);
      setBranding(payload);
    } catch {
      setBranding(null);
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    if (authLoading || !isSignedIn) return;
    void loadSummary();
  }, [authLoading, isSignedIn, loadSummary, workspaceVersion]);

  useEffect(() => {
    if (authLoading || !isSignedIn) {
      setBranding(null);
      return;
    }
    void loadBranding();
  }, [authLoading, isSignedIn, loadBranding, workspaceVersion]);

  useEffect(() => {
    if (authLoading || !isSignedIn) {
      pendingSummaryRefreshRef.current = false;
      return;
    }
    const onCreditsUpdated = () => {
      if (summaryLoading) {
        pendingSummaryRefreshRef.current = true;
        return;
      }
      void loadSummary();
    };
    window.addEventListener("credits:updated", onCreditsUpdated as EventListener);
    return () => window.removeEventListener("credits:updated", onCreditsUpdated as EventListener);
  }, [authLoading, isSignedIn, loadSummary, summaryLoading]);

  // SIGV2-1180: which menu the sidebar renders follows the project the view
  // belongs to, not only the route it sits under. A scan and its history live
  // at /dashboard/audit, outside the project segment, so reaching them from
  // inside a project used to swap the project menu for the workspace one. The
  // project they belong to comes from the `?projectId=` a project's own scan
  // links carry, or from the page itself for a report whose project is only
  // known once the audit record is loaded. No project named means workspace
  // scope, which keeps the workspace-level scan form as it is.
  const setProjectScopeId = useCallback((value: string | number | null) => {
    setRegisteredProjectScopeId(normalizeProjectScopeId(value));
  }, []);
  const projectScope = useMemo(
    () => ({ projectId: registeredProjectScopeId, setProjectId: setProjectScopeId }),
    [registeredProjectScopeId, setProjectScopeId]
  );
  const requestedProjectId = searchParams?.get("projectId") ?? null;
  const projectBasePath = useMemo(
    () => resolveProjectBasePath(pathname, requestedProjectId ?? registeredProjectScopeId),
    [pathname, registeredProjectScopeId, requestedProjectId]
  );
  const projectId = projectBasePath?.split("/").pop() ?? null;
  // signal-MVP removes the "Workspace overview" back link on the workspace
  // overview page itself; everywhere else it returns to /dashboard.
  const showWorkspaceBackLink = pathname !== "/dashboard" && pathname !== "/dashboard/overview";
  const isStaff = userSummary?.role === "admin" || userSummary?.role === "moderator";

  const isBillingPage =
    pathname.startsWith("/dashboard/billing") || pathname.startsWith("/dashboard/account-settings");

  useEffect(() => {
    if (!projectId || authLoading || !isSignedIn) {
      setProject(null);
      return;
    }
    let active = true;
    const loadProject = async () => {
      try {
        const headers = await getAuthHeaders();
        const projectPayload = await fetchProjectById(projectId, headers);
        if (active) setProject(projectPayload);
      } catch {
        if (active) setProject(null);
      }
    };
    void loadProject();
    return () => {
      active = false;
    };
  }, [authLoading, getAuthHeaders, isSignedIn, projectId, workspaceVersion]);

  // The authorised project list for the sidebar switcher is fetched inside
  // SidebarWorkspaceMenu itself; the top bar no longer carries a site picker.

  const primarySections = useMemo(() => {
    const sections = projectBasePath
      ? getProjectNavSections(projectBasePath)
      : workspaceNavSections;
    // Hide sections outside the current role mode's IA. Which modules ship and
    // which are SOON is paired with signal-MVP inside getProjectNavSections;
    // mode filtering only removes items from the IA.
    return filterNavSectionsByMode(sections, roleMode);
  }, [projectBasePath, roleMode]);

  // SignalAppShell's nav shape is presentation-only (icon: ReactNode) so it
  // stays agnostic of navigationConfig.ts's LucideIcon-based NavItem — map
  // here, once, without touching the underlying gating logic above. Labels are
  // resolved through i18next; action items (the approved IA's "Sign out")
  // become buttons wired to logout, never links.
  const signalSections: SignalNavSection[] = useMemo(() => {
    const sections = primarySections.map((section) =>
      toSignalNavSection(section, t, { pathname, onLogout: () => void logout() })
    );
    if (isStaff) sections.push(toSignalNavSection(adminQuickLinks, t, { pathname }));
    return sections;
  }, [isStaff, logout, pathname, primarySections, t]);

  // signal-MVP searchItems(): the palette indexes the same authorised
  // destinations the sidebar renders (already scope- and mode-filtered), plus
  // the workspace quick links while inside a project, plus the approved
  // Actions group. Disabled SOON entries are excluded by the palette itself.
  // Dynamic records (projects, reports) stay out until SIGV2-1020.
  const paletteSections: SignalNavSection[] = useMemo(() => {
    const sections = [...signalSections];
    if (projectBasePath) {
      sections.push(toSignalNavSection(projectWorkspaceQuickLinks, t, { pathname }));
    } else {
      // SIGV2-1189: /dashboard/connections is a real workspace destination
      // with no slot in the approved sidebar IA, so the palette is its door
      // at workspace scope too (inside a project it already sits in the
      // workspace quick links above). The sidebar itself stays untouched.
      const workspaceGroup = sections.findIndex(
        (section) => section.label === t("nav.sectionWorkspace")
      );
      if (workspaceGroup !== -1) {
        sections[workspaceGroup] = {
          ...sections[workspaceGroup],
          items: [
            ...sections[workspaceGroup].items,
            {
              name: t("nav.connections"),
              icon: <Unplug aria-hidden="true" />,
              href: "/dashboard/connections",
            },
          ],
        };
      }
    }

    const actionItems: SignalNavSection["items"] = [
      {
        name: t("signalShell.cookiePreferences"),
        icon: <Cookie aria-hidden="true" />,
        onSelect: openCookieSettings,
      },
    ];
    if (RTL_ENABLED) {
      actionItems.push(
        {
          name: t("signalShell.switchToArabic"),
          icon: <Languages aria-hidden="true" />,
          onSelect: () => changeAppLanguage("ar"),
        },
        {
          name: t("signalShell.switchToEnglish"),
          icon: <Languages aria-hidden="true" />,
          onSelect: () => changeAppLanguage("en"),
        }
      );
    }
    sections.push({ label: t("signalShell.actionsGroup"), items: actionItems });
    return sections;
  }, [openCookieSettings, pathname, projectBasePath, signalSections, t]);

  const projectName = useMemo(() => {
    const trimmedName = project?.name?.trim() ?? "";
    return trimmedName.length > 0 ? trimmedName : null;
  }, [project?.name]);

  const dashboardBrandingStyle = useMemo(() => resolveWorkspaceBrandingStyle(branding), [branding]);
  const brandName = useMemo(() => resolveWorkspaceBrandName(branding), [branding]);

  // User display
  const userEmail = userSummary?.email ?? "";

  useEffect(() => {
    if (authLoading || !isSignedIn) return;
    document.title = resolveDashboardDocumentTitle(pathname, branding, projectName);
    let iconLink = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
    if (!iconLink) {
      iconLink = document.createElement("link");
      iconLink.rel = "icon";
      document.head.appendChild(iconLink);
    }
    const storedDefaultHref = iconLink.getAttribute("data-dashboard-original-href");
    if (!storedDefaultHref) {
      iconLink.setAttribute(
        "data-dashboard-original-href",
        iconLink.getAttribute("href") || asset("/favicon.ico")
      );
    }
    const nextFavicon = branding?.custom_favicon_url?.trim();
    iconLink.href =
      nextFavicon ||
      iconLink.getAttribute("data-dashboard-original-href") ||
      iconLink.getAttribute("href") ||
      asset("/favicon.ico");
  }, [authLoading, branding, isSignedIn, pathname, projectName]);

  return (
    <div
      data-testid="workspace-dashboard-gutter"
      className="min-h-screen signal-canvas"
      style={dashboardBrandingStyle}
      data-workspace-dashboard-shell="true"
    >
      <SignalAppShell
        brandHref="/dashboard"
        brandName="Qiko Signal"
        topLink={
          showWorkspaceBackLink
            ? {
                label: t(workspaceOverviewBackLink.nameKey),
                href: workspaceOverviewBackLink.href,
                icon: <workspaceOverviewBackLink.icon aria-hidden="true" />,
              }
            : undefined
        }
        sections={signalSections}
        footerSlot={
          <SidebarWorkspaceMenu
            email={userEmail}
            onLogout={() => void logout()}
            projectScope={Boolean(projectBasePath)}
            activeProjectId={projectId}
          />
        }
      >
        {/* ══════════════════════════════════════════
            MAIN CONTENT
            ══════════════════════════════════════════ */}
        <div className="relative flex min-h-[calc(100dvh-30px)] flex-col">
          {/* Mobile header */}
          <SignalTopBar
            siteName={projectName}
            siteLabel={
              project?.domain_url?.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "") ||
              projectName ||
              (projectName ? brandName : (pageHeader?.title ?? brandName))
            }
            siteMeta={projectName ? null : pageHeader?.meta}
            crumb={pageHeader?.crumb}
            actions={pageHeader?.actions}
            workspaceDom={!projectName}
            domPill={
              projectName
                ? {
                    domain:
                      project?.domain_url
                        ?.replace(/^https?:\/\/(www\.)?/i, "")
                        .replace(/\/$/, "") || projectName,
                    live: Boolean(project?.last_audit_at),
                    fetchProjects: async () => fetchWorkspaceProjects(await getAuthHeaders()),
                  }
                : undefined
            }
            searchSections={paletteSections}
            menu={
              <MobileDashboardDrawer
                primarySections={primarySections}
                adminSection={isStaff ? adminQuickLinks : undefined}
                projectQuickLinks={projectBasePath ? projectWorkspaceQuickLinks : undefined}
                isProjectContext={Boolean(projectBasePath)}
                activeProjectId={projectId}
                isStaff={isStaff}
                email={userEmail}
                onLogout={() => void logout()}
              />
            }
          />

          {/* Low scan allowance alert. The padding lives on the alert itself so an
             empty alert contributes no gap between `.top` and `.wrap`. */}
          {!isBillingPage && (
            <LowScanAllowanceAlert className="relative z-10 px-3 pt-3 md:px-8 md:pt-5" />
          )}

          {/* Page content */}
          <main
            key={workspaceVersion}
            className="bg-(--paper) text-(--t-1) font-(family-name:--body-font) antialiased relative z-10 flex flex-1 flex-col gap-[22px] scroll-pb-24 p-3 pb-24 md:scroll-pb-8 md:px-8 md:pt-5 md:pb-3.5"
          >
            <WorkspacePageHeaderContext.Provider
              value={{ header: pageHeader, setHeader: setPageHeader }}
            >
              <ProjectScopeContext.Provider value={projectScope}>
                {children}
              </ProjectScopeContext.Provider>
            </WorkspacePageHeaderContext.Provider>
          </main>
          {/* signal-MVP `.site-footer`: pinned after <main>, not in the sidebar. */}
          <SignalAppFooter />
        </div>
      </SignalAppShell>
    </div>
  );
}
