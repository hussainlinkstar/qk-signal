"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, type CSSProperties, type ReactNode } from "react";
import { LayoutGrid, LogOut, FolderOpen, ExternalLink, Settings } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import type { PortalBranding, PortalProjectSummary } from "@/services/portalService";
import { cx } from "@/components/ui/utils";

type PortalShellProps = {
  branding: PortalBranding;
  projects: PortalProjectSummary[];
  children: ReactNode;
};

const defaultPrimary = "#6366F1";
const defaultSecondary = "#22D3EE";

const stripDomainProtocol = (value: string | null) =>
  value ? value.replace(/^https?:\/\//i, "").replace(/\/$/, "") : "Pending domain";

const isActivePath = (pathname: string, href: string) =>
  pathname === href || pathname.startsWith(`${href}/`);

const buildBrandInitials = (value: string) => {
  const normalized = value.trim();
  if (!normalized) {
    return "CP";
  }

  const initials = normalized
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((segment) => segment.charAt(0).toUpperCase())
    .join("");

  return initials || normalized.slice(0, 2).toUpperCase();
};

export default function PortalShell({ branding, projects, children }: PortalShellProps) {
  const pathname = usePathname();
  const { logout, user, isLoading: isAuthLoading } = useAuth();

  const primaryColor = branding.primary_color || defaultPrimary;
  const secondaryColor = branding.secondary_color || defaultSecondary;
  const hidePoweredBy = Boolean(branding.hide_powered_by);
  const brandName = (branding.agency_name || branding.workspace_name || "Client Portal").trim();
  const workspaceName = (branding.workspace_name || brandName).trim();
  const brandInitials = buildBrandInitials(brandName);
  const shellLabel = hidePoweredBy ? "White-label portal" : "Client Portal";
  const subtitle = !hidePoweredBy && workspaceName !== brandName ? workspaceName : null;
  const resolvedTitle =
    branding.custom_page_title || (hidePoweredBy ? brandName : `${workspaceName} - Client Portal`);

  useEffect(() => {
    if (resolvedTitle) {
      document.title = resolvedTitle;
    }
    if (!branding.custom_favicon_url) {
      return;
    }
    let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = branding.custom_favicon_url;
  }, [branding.custom_favicon_url, resolvedTitle]);

  const handleLogout = async () => {
    await logout();
  };

  return (
    <div
      className="min-h-screen bg-(--background) text-(--foreground)"
      style={
        {
          "--portal-primary": primaryColor,
          "--portal-secondary": secondaryColor,
        } as CSSProperties
      }
    >
      {
        null /* <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-24 top-0 h-80 w-80 rounded-full  blur-[110px]" />
        <div className="absolute right-0 top-28 h-96 w-96 rounded-full blur-[130px]" />
      </div> */
      }

      <div className="relative z-10 flex min-h-screen flex-col lg:flex-row">
        <aside className="border-b border-(--border) bg-(--surface) lg:min-h-screen lg:w-80 lg:border-b-0 lg:border-r">
          <div className="border-b border-(--border) px-6 py-6">
            <div className="flex items-center gap-4">
              {branding.custom_logo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={branding.custom_logo_url}
                  alt={brandName}
                  className="h-12 w-12 rounded-lg border-0 bg-(--surface) object-contain p-2 shadow-xs"
                />
              ) : (
                <div className="flex h-12 w-12 items-center justify-center rounded-lg text-sm font-black uppercase text-white shadow-brand bg-(--portal-primary)">
                  {brandInitials}
                </div>
              )}
              <div className="min-w-0">
                <p className="text-[11px] font-bold uppercase tracking-[0.28em] text-(--text-muted)">
                  {shellLabel}
                </p>
                <h1 className="truncate text-xl font-black text-(--foreground)">{brandName}</h1>
                {subtitle ? (
                  <p className="truncate text-sm text-(--text-muted)">{subtitle}</p>
                ) : null}
              </div>
            </div>
          </div>

          <div className="px-4 py-5">
            <nav className="space-y-2">
              <Link
                href="/portal"
                className={cx(
                  "flex items-center gap-3 rounded-xl border px-4 py-3 text-sm font-semibold transition",
                  isActivePath(pathname, "/portal") && !pathname.startsWith("/portal/projects/")
                    ? "border-primary/25 bg-primary/10 text-primary"
                    : "border-(--border) bg-(--surface) text-(--text-soft) hover:border-(--border-hover) hover:bg-(--surface-subtle) hover:text-(--foreground)"
                )}
              >
                <LayoutGrid className="h-4 w-4" />
                <span>Assigned Projects</span>
              </Link>

              {projects.map((project) => (
                <Link
                  key={project.id}
                  href={`/portal/projects/${project.id}`}
                  className={cx(
                    "group flex items-start gap-3 rounded-xl border px-4 py-3 text-sm transition",
                    isActivePath(pathname, `/portal/projects/${project.id}`)
                      ? "border-primary/25 bg-primary/10 text-primary"
                      : "border-(--border) bg-(--surface) text-(--text-soft) hover:border-(--border-hover) hover:bg-(--surface-subtle) hover:text-(--foreground)"
                  )}
                >
                  <FolderOpen className="mt-0.5 h-4 w-4 shrink-0" />
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-(--foreground)">{project.name}</p>
                    <p className="truncate text-xs text-(--text-muted)">
                      {stripDomainProtocol(project.domain_url)}
                    </p>
                  </div>
                </Link>
              ))}
            </nav>
          </div>

          <div className="border-t border-(--border) px-6 py-5 text-sm text-(--text-muted)">
            <Link
              href="/portal/profile"
              className={cx(
                "mb-4 flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold text-(--foreground) transition",
                isActivePath(pathname, "/portal/profile")
                  ? "border-(--border-hover) bg-(--surface-subtle)"
                  : "border-(--border) bg-(--surface) hover:bg-(--surface-subtle)"
              )}
            >
              <Settings className="h-4 w-4" />
              <span>Preferences</span>
            </Link>
            <p className="text-[11px] font-bold uppercase tracking-[0.28em] text-(--text-muted)">
              Signed in
            </p>
            <p className="mt-2 truncate font-semibold text-(--foreground)">
              {isAuthLoading ? (
                <span className="inline-block h-4 w-32 animate-pulse rounded bg-(--surface-subtle)" />
              ) : (
                (user?.email ?? "Portal user")
              )}
            </p>
            <button
              type="button"
              onClick={() => void handleLogout()}
              className="mt-4 inline-flex items-center gap-2 rounded-lg border-0 bg-(--surface) px-4 py-2 text-sm font-semibold text-(--foreground) transition hover:bg-(--surface-subtle)"
            >
              <LogOut className="h-4 w-4" />
              <span>Sign Out</span>
            </button>
          </div>
        </aside>

        <div className="flex-1">
          <header className="border-b border-(--border) px-6 py-5 md:px-10">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.28em] text-(--text-muted)">
                  Live reporting access
                </p>
                <p className="mt-2 max-w-3xl text-sm text-(--text-soft)">
                  Review current scores, recent trends, and exported Jira tasks for your assigned
                  properties.
                </p>
              </div>
              {projects.length === 1 && projects[0]?.domain_url ? (
                <a
                  href={projects[0].domain_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg border-0 bg-(--surface) px-4 py-2 text-sm font-semibold text-(--foreground) transition hover:bg-(--surface-subtle)"
                >
                  <span>Visit site</span>
                  <ExternalLink className="h-4 w-4" />
                </a>
              ) : null}
            </div>
          </header>

          <main className="px-6 py-8 md:px-10 md:py-10">{children}</main>

          <footer className="border-t border-(--border) bg-(--surface) px-6 py-4 text-xs text-(--text-muted) md:px-10">
            <p>
              © {new Date().getFullYear()} {workspaceName}
              {!hidePoweredBy ? " · Powered by Qiko Signal" : ""}
            </p>
          </footer>
        </div>
      </div>
    </div>
  );
}
