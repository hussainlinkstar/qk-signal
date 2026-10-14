import type { LucideIcon } from "lucide-react";
import {
  Activity,
  CircleArrowLeft,
  CodeXml,
  CreditCard,
  Globe,
  LayoutDashboard,
  LogOut,
  Network,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  SquareCheck,
  TrendingUp,
  Unplug,
  User,
  Users,
} from "lucide-react";
import { type RoleMode, shownInMode } from "@/lib/roleMode";

export type NavItem = {
  name: string;
  /**
   * i18n key for the rendered label. When present, consumers resolve the label
   * through i18next (`item.nameKey ? t(item.nameKey) : item.name`); `name`
   * stays as the English source string used by tests and untranslated callers.
   */
  nameKey?: string;
  /**
   * Route the item links to. Action items (see `action`) have no href and must
   * never be rendered as links.
   */
  href?: string;
  icon: LucideIcon;
  badge?: string;
  badgeKey?: string;
  disabled?: boolean;
  /**
   * Non-navigating action. `"logout"` ends the session; consumers wire the
   * actual handler. The approved IA carries "Sign out" as a nav entry in the
   * Account group, so it lives here rather than in page chrome.
   */
  action?: "logout";
  /**
   * Canonical section key (see `roleMode.ts` MODE_SECTIONS) used for mode-aware
   * IA gating. Items without a `sectionKey` are always shown (never hidden by
   * mode); mode gating only hides from the IA and never bypasses plan/role gates.
   */
  sectionKey?: string;
};

export type NavSection = {
  label: string;
  /** i18n key for the rendered section label; see `NavItem.nameKey`. */
  labelKey?: string;
  items: NavItem[];
};

/**
 * Approved SIGV2-1033 information architecture (signal-MVP `mountSidebar`).
 * This restores the sidebar the approved design ships, reverting the R1 cuts
 * (3908d523, 287ecfd8) that removed badged SOON entries, Workspace Settings
 * and Developer Hub:
 *
 * - Project scope: Intelligence (Dashboard, AIO score, SEO score, Competitors,
 *   Entities SOON), Automation (Tasks SOON), Account (Settings, Sign out).
 * - Workspace scope: Workspace (Overview, Workspace Settings, My Profile,
 *   Billing, Developer Hub), Account (Sign out).
 *
 * SOON entries are deliberately visible but non-navigating: the approved
 * design shows them with a "Soon" badge, and the rendered item must announce
 * itself as unavailable to assistive technology. `Fixes` is intentionally NOT
 * a sidebar entry in the approved design; it is reached from the dashboard
 * actions and the AIO drilldown. The mockup's `Components` entry is an
 * internal catalogue and never appears in the customer IA. Restoring an entry
 * is an IA change only: it never relaxes a plan, role or tenant check.
 */
export const workspaceNavSections: NavSection[] = [
  {
    label: "Workspace",
    labelKey: "nav.sectionWorkspace",
    items: [
      {
        name: "Overview",
        nameKey: "nav.overview",
        href: "/dashboard",
        icon: LayoutDashboard,
        sectionKey: "overview",
      },
      {
        name: "Workspace Settings",
        nameKey: "nav.workspaceSettings",
        href: "/dashboard/settings",
        icon: Settings,
      },
      {
        name: "My Profile",
        nameKey: "nav.myProfile",
        href: "/dashboard/account-settings",
        icon: User,
      },
      {
        name: "Billing",
        nameKey: "nav.billing",
        href: "/dashboard/billing",
        icon: CreditCard,
      },
      {
        name: "Developer Hub",
        nameKey: "nav.developerHub",
        href: "/dashboard/developer",
        icon: CodeXml,
      },
    ],
  },
  {
    label: "Account",
    labelKey: "nav.sectionAccount",
    items: [{ name: "Sign out", nameKey: "nav.signOut", icon: LogOut, action: "logout" }],
  },
];

export function getProjectNavSections(basePath: string): NavSection[] {
  return [
    {
      label: "Intelligence",
      labelKey: "nav.sectionIntelligence",
      items: [
        { name: "Dashboard", nameKey: "nav.dashboard", href: basePath, icon: LayoutDashboard },
        {
          name: "AIO score",
          nameKey: "nav.aioScore",
          href: `${basePath}/ai-answers`,
          icon: Sparkles,
        },
        { name: "SEO score", nameKey: "nav.seoScore", href: `${basePath}/google`, icon: Globe },
        {
          name: "Competitors",
          nameKey: "nav.competitors",
          href: `${basePath}/competitors`,
          icon: TrendingUp,
        },
        {
          name: "Entities",
          nameKey: "nav.entities",
          icon: Network,
          disabled: true,
          badge: "SOON",
          badgeKey: "nav.soon",
        },
      ],
    },
    {
      label: "Automation",
      labelKey: "nav.sectionAutomation",
      items: [
        {
          name: "Tasks",
          nameKey: "nav.tasks",
          icon: SquareCheck,
          disabled: true,
          badge: "SOON",
          badgeKey: "nav.soon",
        },
      ],
    },
    {
      label: "Account",
      labelKey: "nav.sectionAccount",
      items: [
        {
          name: "Settings",
          nameKey: "nav.settings",
          href: `${basePath}/settings`,
          icon: SlidersHorizontal,
        },
        { name: "Sign out", nameKey: "nav.signOut", icon: LogOut, action: "logout" },
      ],
    },
  ];
}

/**
 * The "Workspace overview" link the approved design pins at the top of the
 * sidebar, above the nav sections, on every page except the workspace
 * overview itself. Icon mirrors the mockup's left-arrow-in-a-circle.
 */
export const workspaceOverviewBackLink = {
  name: "Workspace overview",
  nameKey: "nav.workspaceOverview",
  href: "/dashboard",
  icon: CircleArrowLeft,
};

export const projectWorkspaceQuickLinks: NavSection = {
  label: "Workspace",
  labelKey: "nav.sectionWorkspace",
  items: [
    {
      name: "Workspace Overview",
      nameKey: "nav.workspaceOverview",
      href: "/dashboard",
      icon: LayoutDashboard,
    },
    { name: "Billing", nameKey: "nav.billing", href: "/dashboard/billing", icon: CreditCard },
    {
      name: "Workspace Settings",
      nameKey: "nav.workspaceSettings",
      href: "/dashboard/settings",
      icon: SlidersHorizontal,
    },
    // SIGV2-1189: the Connections Hub has no slot in the approved sidebar IA,
    // so the workspace quick links are its consistent door inside a project.
    {
      name: "Connections",
      nameKey: "nav.connections",
      href: "/dashboard/connections",
      icon: Unplug,
    },
  ],
};

export const adminQuickLinks: NavSection = {
  label: "Admin",
  items: [
    { name: "Admin Center", href: "/admin/overview", icon: ShieldAlert },
    { name: "User Management", href: "/admin/users", icon: Users },
    { name: "System Status", href: "/admin/system-status", icon: Activity },
    { name: "General Settings", href: "/admin/settings/general", icon: SlidersHorizontal },
  ],
};

const normalizeNavPath = (value: string): string =>
  value.length > 1 ? value.replace(/\/+$/g, "") : value;

export function isRouteActive(pathname: string, href: string): boolean {
  const normalizedPathname = normalizeNavPath(pathname);
  const normalizedHref = normalizeNavPath(href);

  if (normalizedHref === "/dashboard") {
    return normalizedPathname === "/dashboard" || normalizedPathname === "/dashboard/overview";
  }

  if (/^\/dashboard\/projects\/[^/]+$/.test(normalizedHref)) {
    return (
      normalizedPathname === normalizedHref || normalizedPathname === `${normalizedHref}/overview`
    );
  }

  return (
    normalizedPathname === normalizedHref || normalizedPathname.startsWith(`${normalizedHref}/`)
  );
}

export function findProjectBasePath(pathname: string): string | null {
  const match = pathname.match(/^\/dashboard\/projects\/[^/]+/);
  return match ? match[0] : null;
}

/**
 * Routes that show one project's own data while living outside the
 * `/dashboard/projects/<id>` segment: the scan page with its history
 * disclosure, and a scan's report. Reached from inside a project they name
 * that project - the `?projectId=` a project's own scan links carry, or the
 * project the report's audit belongs to - and the sidebar has to stay on that
 * project's menu (SIGV2-1180). Reached from the workspace overview they name
 * no project at all, and the workspace menu is then the correct one: that is
 * the approved workspace-level scan form.
 */
const PROJECT_SCOPED_ROUTES = ["/dashboard/audit"] as const;

export function isProjectScopedRoute(pathname: string): boolean {
  const normalized = normalizeNavPath(pathname);
  return PROJECT_SCOPED_ROUTES.some(
    (route) => normalized === route || normalized.startsWith(`${route}/`)
  );
}

/**
 * A project id reduced to a bare positive integer, or null.
 *
 * Every value that reaches here is supplied by something outside this module
 * (a query string, an API payload) and the result is interpolated into the
 * sidebar's hrefs, so anything that is not a positive integer is rejected
 * rather than escaped: `?projectId=../../admin` resolves to no scope at all.
 * Resolving a scope grants nothing - each destination keeps its own workspace,
 * plan and role checks.
 */
export function normalizeProjectScopeId(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (!/^\d+$/.test(raw)) return null;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed > 0 ? String(parsed) : null;
}

/**
 * The project base path the sidebar menu is built from: the one in the
 * pathname when the route sits inside the project segment, otherwise the
 * project a project-scoped route names (see `PROJECT_SCOPED_ROUTES`). Null
 * means workspace scope.
 */
export function resolveProjectBasePath(
  pathname: string,
  projectScopeId?: string | number | null
): string | null {
  const fromPathname = findProjectBasePath(pathname);
  if (fromPathname) return fromPathname;
  if (!isProjectScopedRoute(pathname)) return null;
  const scopeId = normalizeProjectScopeId(projectScopeId);
  return scopeId ? `/dashboard/projects/${scopeId}` : null;
}

export function flattenNavSections(sections: NavSection[]): NavItem[] {
  return sections.flatMap((section) => section.items);
}

/** Resolve a nav item's display label through i18next when it carries a key. */
export function resolveNavName(item: NavItem, t: (key: string) => string): string {
  return item.nameKey ? t(item.nameKey) : item.name;
}

/** Resolve a nav section's display label through i18next when it carries a key. */
export function resolveNavLabel(section: NavSection, t: (key: string) => string): string {
  return section.labelKey ? t(section.labelKey) : section.label;
}

/** Resolve a badge's display text through i18next when it carries a key. */
export function resolveNavBadge(item: NavItem, t: (key: string) => string): string | undefined {
  if (!item.badge && !item.badgeKey) return undefined;
  return item.badgeKey ? t(item.badgeKey) : item.badge;
}

/**
 * Hide nav items that are not part of the current role mode's IA. An item is
 * kept when it has no `sectionKey` (default-to-shown) or when `shownInMode`
 * returns true for its section. Sections left with no visible items are dropped.
 *
 * This is purely an IA filter: it never adds items or bypasses the existing
 * plan/role gating already applied to each item (e.g. `withProjectFeatureLock`).
 */
export function filterNavSectionsByMode(sections: NavSection[], mode: RoleMode): NavSection[] {
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) => item.sectionKey === undefined || shownInMode(item.sectionKey, mode)
      ),
    }))
    .filter((section) => section.items.length > 0);
}
