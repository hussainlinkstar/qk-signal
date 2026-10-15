"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createPortal } from "react-dom";
import {
  Activity,
  AppWindow,
  Bell,
  Bot,
  Building2,
  ChevronRight,
  CreditCard,
  Crown,
  DollarSign,
  Gauge,
  Globe,
  Database,
  KeyRound,
  LayoutDashboard,
  LayoutTemplate,
  Lock,
  Mail,
  Menu,
  MessageSquare,
  Monitor,
  Receipt,
  ScrollText,
  Server,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  SlidersHorizontal,
  ToggleLeft,
  Users,
  Wrench,
  X,
} from "lucide-react";
import { AdminGuardProvider, useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { AdminAlertBell } from "@/components/admin/AdminAlertBell";
import { useAuth } from "@/components/auth/custom-auth";
import SidebarWorkspaceMenu from "@/components/app/SidebarWorkspaceMenu";
import SignalAppShell, {
  ITEM_ACTIVE,
  ITEM_CLASSES,
  ITEM_INACTIVE,
  type SignalNavSection,
} from "@/components/signal/SignalAppShell";
import SignalTopBar from "@/components/signal/SignalTopBar";
import SignalCrumb from "@/components/signal/SignalCrumb";
import SignalAppFooter from "@/components/signal/SignalAppFooter";
import {
  WorkspacePageHeaderContext,
  type WorkspacePageHeader,
} from "@/components/dashboard/workspacePageHeader";
import { cx } from "@/components/ui/utils";

/* ------------------------------------------------------------------ */
/*  Grouped navigation sections                                       */
/* ------------------------------------------------------------------ */

interface NavItem {
  name: string;
  href: string;
  icon: React.ReactNode;
  requireAdmin?: boolean;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    label: "Overview",
    items: [
      { name: "Dashboard", href: "/admin/overview", icon: <LayoutDashboard size={18} /> },
      { name: "Health & Status", href: "/admin/system-status", icon: <Activity size={18} /> },
    ],
  },
  {
    label: "Identity & Access",
    items: [
      {
        name: "Workspaces",
        href: "/admin/workspaces",
        icon: <Building2 size={18} />,
        requireAdmin: true,
      },
      {
        name: "User Management",
        href: "/admin/users",
        icon: <Users size={18} />,
        requireAdmin: true,
      },
      {
        name: "Security Logs",
        href: "/admin/security",
        icon: <ShieldCheck size={18} />,
        requireAdmin: true,
      },
    ],
  },
  {
    label: "Billing & Usage",
    items: [
      {
        name: "Subscriptions",
        href: "/admin/subscriptions",
        icon: <Receipt size={18} />,
        requireAdmin: true,
      },
      {
        name: "Invoices & Payments",
        href: "/admin/payments",
        icon: <CreditCard size={18} />,
        requireAdmin: true,
      },
      {
        name: "Quotas & Commitments",
        href: "/admin/commitments",
        icon: <Gauge size={18} />,
        requireAdmin: true,
      },
      { name: "AI Spend & Usage", href: "/admin/costs", icon: <DollarSign size={18} /> },
      {
        name: "Billing Configuration",
        href: "/admin/settings/payments",
        icon: <SlidersHorizontal size={18} />,
        requireAdmin: true,
      },
    ],
  },
  {
    label: "Monitoring & Telemetry",
    items: [
      { name: "Infrastructure", href: "/admin/infrastructure", icon: <Monitor size={18} /> },
      { name: "APM & Traces", href: "/admin/observability", icon: <Activity size={18} /> },
      { name: "Active Alerts", href: "/admin/alerts", icon: <Bell size={18} /> },
      { name: "Model Lifecycle", href: "/admin/model-lifecycle", icon: <Sparkles size={18} /> },
      { name: "Claim Feedback", href: "/admin/claim-feedback", icon: <MessageSquare size={18} /> },
    ],
  },
  {
    label: "Platform Settings",
    items: [
      {
        name: "Pricing Tiers & Features",
        href: "/admin/plans",
        icon: <Crown size={18} />,
        requireAdmin: true,
      },
      {
        name: "Runtime Configuration",
        href: "/admin/config",
        icon: <Wrench size={18} />,
        requireAdmin: true,
      },
      {
        name: "Global Settings",
        href: "/admin/settings/general",
        icon: <Settings size={18} />,
        requireAdmin: true,
      },
      {
        name: "Maintenance Mode",
        href: "/admin/maintenance",
        icon: <ToggleLeft size={18} />,
        requireAdmin: true,
      },
    ],
  },
  {
    label: "Integrations & Email",
    items: [
      {
        name: "AI Models & API Keys",
        href: "/admin/settings/ai-models",
        icon: <Bot size={18} />,
        requireAdmin: true,
      },
      {
        name: "OAuth Clients",
        href: "/admin/settings/oauth",
        icon: <Lock size={18} />,
        requireAdmin: true,
      },
      {
        name: "Integration Health",
        href: "/admin/settings/configuration",
        icon: <KeyRound size={18} />,
        requireAdmin: true,
      },
      {
        name: "Email Configuration",
        href: "/admin/settings/email-config",
        icon: <Mail size={18} />,
        requireAdmin: true,
      },
      {
        name: "Email Footer & Social",
        href: "/admin/settings/email-footer",
        icon: <Globe size={18} />,
        requireAdmin: true,
      },
    ],
  },
  {
    label: "Data & Compliance",
    items: [
      {
        name: "Activity Logs",
        href: "/admin/audit-trail",
        icon: <ScrollText size={18} />,
        requireAdmin: true,
      },
      {
        name: "Data Privacy (GDPR)",
        href: "/admin/gdpr",
        icon: <Shield size={18} />,
        requireAdmin: true,
      },
      {
        name: "Data Lifecycle",
        href: "/admin/audit-retention",
        icon: <Database size={18} />,
        requireAdmin: true,
      },
    ],
  },
  {
    label: "Operations & Queues",
    items: [
      { name: "Job Queue", href: "/admin/jobs", icon: <Server size={18} /> },
      { name: "Email Delivery", href: "/admin/email-outbox", icon: <Mail size={18} /> },
      {
        name: "Email Templates",
        href: "/admin/email-templates",
        icon: <LayoutTemplate size={18} />,
      },
      { name: "Audit History", href: "/admin/audit-application", icon: <AppWindow size={18} /> },
    ],
  },
];

const allNavItems = navSections.flatMap((s) => s.items);

function filterSectionsForRole(sections: NavSection[], isAdmin: boolean): NavSection[] {
  if (isAdmin) return sections;
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => !item.requireAdmin),
    }))
    .filter((section) => section.items.length > 0);
}

/* ------------------------------------------------------------------ */
/*  Nav link component, clean, no border, subtle glow on active      */
/* ------------------------------------------------------------------ */

function AdminNavLink({
  item,
  isActive,
  onClick,
}: {
  item: NavItem;
  isActive: boolean;
  onClick?: () => void;
}) {
  return (
    <Link
      href={item.href}
      onClick={onClick}
      aria-current={isActive ? "page" : undefined}
      // Drawer rows are the SignalAppShell item contract; `min-h-11` keeps the
      // mobile 44px touch target the shell comment reserves for the drawer.
      className={cx(ITEM_CLASSES, "min-h-11", isActive ? ITEM_ACTIVE : ITEM_INACTIVE)}
    >
      <span className="flex-none [&_svg]:h-[17px] [&_svg]:w-[17px] [&_svg]:stroke-[1.9]">
        {item.icon}
      </span>
      <span className="min-w-0 truncate leading-snug">{item.name}</span>
    </Link>
  );
}

/* ------------------------------------------------------------------ */
/*  Collapsible section header                                        */
/* ------------------------------------------------------------------ */

function SectionLabel({
  children,
  expanded,
  onToggle,
}: {
  children: React.ReactNode;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center justify-between rounded-md px-2.5 pb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.12em] text-(--t-3) select-none transition-colors hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
      aria-expanded={expanded}
    >
      <span>{children}</span>
      <ChevronRight
        size={12}
        className={`transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
      />
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Sidebar content (shared between desktop + mobile)                 */
/* ------------------------------------------------------------------ */

function SidebarNav({
  pathname,
  sections,
  onNavigate,
}: {
  pathname: string;
  sections: NavSection[];
  onNavigate?: () => void;
}) {
  /* All sections expanded by default */
  const allLabels = useMemo(() => new Set(sections.map((s) => s.label)), [sections]);

  const [expanded, setExpanded] = useState<Set<string>>(allLabels);

  /* Ensure new sections are expanded if sections list changes */
  useEffect(() => {
    setExpanded((prev) => {
      const next = new Set(prev);
      for (const label of allLabels) next.add(label);
      return next;
    });
  }, [allLabels]);

  const toggle = useCallback((label: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }, []);

  return (
    <nav className="flex flex-col" aria-label="Admin navigation">
      {sections.map((section, index) => {
        const isExpanded = expanded.has(section.label);
        return (
          <div
            key={section.label}
            className={index === 0 ? "pt-[11px]" : "mt-2 border-t border-(--line-2) pt-4"}
          >
            <SectionLabel expanded={isExpanded} onToggle={() => toggle(section.label)}>
              {section.label}
            </SectionLabel>
            {isExpanded && (
              <div>
                {section.items.map((item) => {
                  const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
                  return (
                    <AdminNavLink
                      key={item.href}
                      item={item}
                      isActive={isActive}
                      onClick={onNavigate}
                    />
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

/* ------------------------------------------------------------------ */
/*  Main layout                                                       */
/* ------------------------------------------------------------------ */

export default function AdminShell({ children }: { children: React.ReactNode }) {
  return (
    <AdminGuardProvider>
      <AdminLayoutInner>{children}</AdminLayoutInner>
    </AdminGuardProvider>
  );
}

function AdminLayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAdmin, user: adminUser } = useAdminAccess();
  const { logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [pageHeader, setPageHeader] = useState<WorkspacePageHeader>(null);
  const [mounted, setMounted] = useState(false);
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);

  const filteredSections = useMemo(() => filterSectionsForRole(navSections, isAdmin), [isAdmin]);

  const activeItem = useMemo(
    () =>
      allNavItems.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`)),
    [pathname]
  );

  const activeSection = useMemo(
    () =>
      navSections.find((s) =>
        s.items.some((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))
      ),
    [pathname]
  );

  const roleLabel = isAdmin ? "Admin" : "Moderator";

  // SignalAppShell's nav shape is presentation-only (icon: ReactNode); admin's
  // local NavItem already stores pre-rendered icon elements, so this mapping
  // is a straight pass-through plus the active-state computed the same way
  // AdminNavLink already computes it (kept identical, not re-derived).
  const signalSections: SignalNavSection[] = useMemo(
    () =>
      filteredSections.map((section) => ({
        label: section.label,
        items: section.items.map((item) => ({
          name: item.name,
          href: item.href,
          icon: item.icon,
          active: pathname === item.href || pathname.startsWith(`${item.href}/`),
        })),
      })),
    [filteredSections, pathname]
  );

  /* Mount guard for portal */
  useEffect(() => {
    setMounted(true);
  }, []);

  /* Close on route change */
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  /* Lock scroll + keyboard when drawer is open */
  useEffect(() => {
    if (!mobileOpen) return;

    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileOpen(false);
        hamburgerRef.current?.focus();
      }
    };

    document.addEventListener("keydown", handleKey);

    /* Focus first focusable inside drawer */
    requestAnimationFrame(() => {
      const el = drawerRef.current?.querySelector<HTMLElement>("a[href], button");
      el?.focus();
    });

    return () => {
      document.body.style.overflow = prev;
      document.removeEventListener("keydown", handleKey);
    };
  }, [mobileOpen]);

  const closeMobile = useCallback(() => setMobileOpen(false), []);

  return (
    <>
      <SignalAppShell
        brandHref="/admin/overview"
        brandName="Qiko"
        brandSub="Admin"
        sections={signalSections}
        footerSlot={
          <SidebarWorkspaceMenu
            email={adminUser?.email ?? ""}
            onLogout={() => void logout()}
            fetchEnabled={false}
            kindLabel={roleLabel}
            label={`${roleLabel} workspace`}
            note="Access restricted to approved operators. All actions are audited."
          />
        }
      >
        {/* ── Main content area ────────────────────────────────── */}
        <div className="relative flex min-h-[calc(100dvh-30px)] flex-col">
          <SignalTopBar
            crumb={
              <SignalCrumb
                items={[
                  { label: roleLabel },
                  ...(activeSection ? [{ label: activeSection.label }] : []),
                  { label: activeItem?.name ?? "Overview" },
                ]}
              />
            }
            searchSections={signalSections}
            actions={
              <>
                {pageHeader?.actions}
                <AdminAlertBell />
              </>
            }
            menu={
              <button
                ref={hamburgerRef}
                type="button"
                onClick={() => setMobileOpen(true)}
                className="inline-flex h-11 w-11 items-center justify-center rounded-lg border-0 bg-white text-(--t-1) transition-colors hover:bg-(--line-2) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2 lg:hidden"
                aria-expanded={mobileOpen}
                aria-label="Open admin menu"
              >
                <Menu size={20} />
              </button>
            }
          />

          <main className="bg-(--paper) text-(--t-1) font-(family-name:--body-font) antialiased relative z-10 flex flex-1 flex-col gap-[22px] scroll-pb-24 p-3 pb-24 md:scroll-pb-8 md:px-8 md:pt-5 md:pb-3.5">
            <WorkspacePageHeaderContext.Provider
              value={{ header: pageHeader, setHeader: setPageHeader }}
            >
              {children}
            </WorkspacePageHeaderContext.Provider>
          </main>

          {/* signal-MVP `.site-footer`: pinned after <main>, not in the sidebar. */}
          <SignalAppFooter />
        </div>
      </SignalAppShell>

      {/* ── Mobile drawer (portal) ───────────────────────────── */}
      {mounted && mobileOpen
        ? createPortal(
            // The portal mounts on document.body, outside SignalAppShell's
            // [data-signal-theme], so it must carry the theme itself or it
            // inherits the dark :root tokens.
            <div data-signal-theme className="fixed inset-0 z-mobile-menu lg:hidden">
              {/* Backdrop */}
              <div
                className="absolute inset-0 bg-(--overlay-backdrop) animate-in fade-in duration-150 motion-reduce:animate-none"
                aria-hidden
                onClick={closeMobile}
              />

              {/* Drawer panel, slides from left */}
              <div
                ref={drawerRef}
                role="dialog"
                aria-modal="true"
                aria-label="Admin navigation"
                className="absolute inset-y-0 start-0 flex w-[min(320px,85vw)] max-w-full flex-col border-e border-(--line) bg-(--panel) animate-in fade-in slide-in-from-left rtl:slide-in-from-right duration-200 motion-reduce:animate-none"
              >
                {/* Drawer header */}
                <header className="flex items-center justify-between border-b border-(--line) px-5 py-4">
                  <div>
                    <p className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.12em] text-(--t-3)">
                      {roleLabel}
                    </p>
                    <h2 className="mt-0.5 font-(family-name:--disp) text-base font-bold tracking-[-0.01em] text-(--t-1)">
                      Navigation
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={closeMobile}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-md text-(--t-3) transition-colors hover:bg-(--line-2) hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
                    aria-label="Close admin menu"
                  >
                    <X size={16} />
                  </button>
                </header>

                {/* Scrollable nav */}
                <div className="flex-1 overflow-y-auto px-2.5 py-3">
                  <SidebarNav
                    pathname={pathname}
                    sections={filteredSections}
                    onNavigate={closeMobile}
                  />
                </div>

                {/* Admin badge */}
                <div className="mx-3 mb-3 rounded-[14px] border-0 bg-[#EEF1F6] px-3 py-2.5 text-xs">
                  <div className="flex items-center gap-2 font-semibold text-(--t-1)">
                    <ShieldCheck size={14} className="text-(--purple)" />
                    <span>{roleLabel} workspace</span>
                  </div>
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  );
}
