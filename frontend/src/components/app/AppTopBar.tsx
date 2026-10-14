"use client";

import Link from "next/link";
import { Suspense } from "react";
import {
  SignedIn,
  SignedOut,
  UserButton,
  UserAvatar,
  useAuth,
} from "@/components/auth/custom-auth";
import { useTranslation } from "react-i18next";
import { usePathname } from "next/navigation";
import { ChevronRight, LogOut } from "lucide-react";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import ActiveAuditChip from "@/components/app/ActiveAuditChip";
import { TopBarNav, TopBarNavLink } from "@/components/app/TopBarNav";
import TopBarShell from "@/components/app/TopBarShell";
import MobileHeaderMenu from "@/components/navigation/MobileHeaderMenu";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { getHeaderNavLinkClassName } from "@/components/navigation/headerNavStyles";
import { buttonClasses } from "@/components/ui/Button";
import {
  findProjectBasePath,
  flattenNavSections,
  getProjectNavSections,
  resolveNavLabel,
  resolveNavName,
  workspaceNavSections,
} from "@/components/navigation/navigationConfig";

export default function AppTopBar() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const pathname = usePathname();
  // On dashboard routes the collapsible sidebar provides navigation; keep the top bar thin (qiko-style).
  const isDashboardRoute = pathname === "/dashboard" || pathname.startsWith("/dashboard/");
  // Admin routes render their own SignalTopBar inside AdminShell.
  const isAdminRoute = pathname === "/admin" || pathname.startsWith("/admin/");

  // On dashboard routes the sidebar owns the logo and all navigation.
  // Hiding the top bar here matches the app.qiko.ai user area which has no top bar.
  if (isDashboardRoute || isAdminRoute) {
    return null;
  }
  const projectBasePath = findProjectBasePath(pathname);
  const navSections = projectBasePath
    ? getProjectNavSections(projectBasePath)
    : workspaceNavSections;
  // Action nav items (e.g. the approved IA's "Sign out") have no href and are
  // never rendered as links; the mobile menu has its own Log Out row.
  const desktopNavItems = flattenNavSections(navSections)
    .filter((item) => item.href)
    .slice(0, 4);

  const mobileNavContent = (
    <>
      {navSections.map((section) => {
        const links = section.items.filter((item) => item.href);
        if (!links.length) return null;
        return (
          <div key={section.label} className="px-5 py-2">
            <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.2em] text-(--text-muted)">
              {resolveNavLabel(section, t)}
            </p>
            <div className="space-y-1">
              {links.map((item) => (
                <Link
                  key={item.href}
                  href={item.href!}
                  className={getHeaderNavLinkClassName({ mobile: true })}
                >
                  {resolveNavName(item, t)}
                </Link>
              ))}
            </div>
          </div>
        );
      })}
    </>
  );

  const desktopActions = (
    <>
      {/* Flag-gated: renders nothing unless NEXT_PUBLIC_ENABLE_RTL is on. */}
      <LanguageSwitcher />
      <SignedIn>
        <ActiveAuditChip />
        <UserButton />
      </SignedIn>
      <SignedOut>
        <Link href="/login" className={buttonClasses({ variant: "ghost", size: "md" })}>
          {t("appNav.signIn")}
        </Link>
      </SignedOut>
    </>
  );

  const initials = user?.name
    ? user.name
        .split(" ")
        .map((n: string) => n[0])
        .join("")
        .toUpperCase()
    : (user?.email?.[0]?.toUpperCase() ?? "?");

  const mobileUserContent = user ? (
    <>
      {/* User card row, tappable, links to account settings */}
      <Link
        href="/dashboard/account-settings"
        className="flex items-center gap-3.5 px-5 py-4 transition-colors hover:bg-(--surface-subtle)"
      >
        <UserAvatar
          avatarUrl={user.avatar_url}
          initials={initials}
          size="md"
          authProvider={user.auth_provider}
        />
        <div className="min-w-0 flex-1">
          <p className="text-[0.95rem] font-bold text-(--foreground) leading-tight">
            Hi, {user.name || "there"}
          </p>
          <p className="mt-0.5 truncate text-xs text-(--text-muted)">{user.email}</p>
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-(--text-muted)" />
      </Link>
      {/* Log Out, standalone row */}
      <button
        type="button"
        data-mobile-menu-close="true"
        onClick={() => void logout()}
        className="flex w-full items-center gap-3 px-5 py-3 text-sm font-bold text-(--text-soft) transition-colors hover:bg-(--surface-subtle) hover:text-(--foreground)"
      >
        <LogOut className="h-4 w-4 text-(--text-muted)" />
        Log Out
      </button>
    </>
  ) : null;

  const mobileActionContent = (
    <SignedOut>
      <div className="px-5 py-3">
        <Link
          href="/login"
          className={buttonClasses({
            variant: "primary",
            size: "md",
            className: "w-full justify-center",
          })}
          data-mobile-menu-close="true"
        >
          {t("appNav.signIn")}
        </Link>
      </div>
    </SignedOut>
  );

  return (
    <TopBarShell
      logo={
        <Link
          href="/dashboard"
          aria-label="Qiko Signal dashboard"
          className="flex min-w-0 items-center"
        >
          <SignalBrandLockup />
        </Link>
      }
      nav={
        isDashboardRoute ? null : (
          <TopBarNav>
            {desktopNavItems.map((item) => (
              <TopBarNavLink key={item.href} href={item.href!}>
                {resolveNavName(item, t)}
              </TopBarNavLink>
            ))}
          </TopBarNav>
        )
      }
      actions={
        <>
          <Suspense
            fallback={<div className="h-11 w-11 rounded-xl bg-white/5 animate-pulse md:hidden" />}
          >
            <MobileHeaderMenu
              menuLabel={t("appNav.openMenu", { defaultValue: "Open app menu" })}
              userContent={mobileUserContent}
              navContent={mobileNavContent}
              actionContent={mobileActionContent}
            />
          </Suspense>
          <div className="hidden items-center gap-3 md:flex">{desktopActions}</div>
        </>
      }
    />
  );
}
