"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { SignedIn, SignedOut, UserButton, useAuth } from "@/components/auth/custom-auth";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import { ChevronRight, LogOut } from "lucide-react";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import MobileHeaderMenu from "@/components/navigation/MobileHeaderMenu";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import {
  getHeaderNavLinkClassName,
  getHeaderUtilityLinkClassName,
} from "@/components/navigation/headerNavStyles";
import { resolveQikoSiteUrl } from "@/lib/qiko-site-url";

const NAV_LINK_CLASS =
  "relative text-sm font-medium text-(--text-muted) transition-colors duration-200 hover:text-(--foreground)";

// Signal is one of two products on the shared Qiko marketing site (qiko-website-v2); these link
// back to the sibling product's pages there. SIGNAL-1009.
const qikoSiteUrl = resolveQikoSiteUrl();
const QIKO_HOME_URL = qikoSiteUrl;
const QIKO_LABS_URL = `${qikoSiteUrl}/labs`;

function MobileNavSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="px-5 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wider text-(--text-muted)">
        {title}
      </p>
      <div className="mt-2 rounded-xl border border-(--border) bg-(--surface) p-1 shadow-xs">
        {children}
      </div>
    </div>
  );
}

export default function MarketingHeader() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const router = useRouter();

  const mobileNavContent = (
    <>
      <MobileNavSection title={t("nav.qikoPlatform", { defaultValue: "Qiko" })}>
        <Link href={QIKO_HOME_URL} className={getHeaderNavLinkClassName({ mobile: true })}>
          {t("nav.qiko", { defaultValue: "Home" })}
        </Link>
        <Link href={QIKO_LABS_URL} className={getHeaderNavLinkClassName({ mobile: true })}>
          {t("nav.labs", { defaultValue: "Labs" })}
        </Link>
      </MobileNavSection>
    </>
  );

  const desktopActions = (
    <>
      {/* Flag-gated: renders nothing unless NEXT_PUBLIC_ENABLE_RTL is on. */}
      <LanguageSwitcher />
      <SignedIn>
        <div className="flex items-center gap-4">
          <UserButton afterSignOutUrl="/" />
        </div>
      </SignedIn>
      <SignedOut>
        <Link href="/login" className="text-sm font-medium text-(--foreground) transition-colors">
          {t("nav.login")}
        </Link>
        <Link
          href="/register"
          className="inline-flex items-center justify-center gap-2 rounded-full bg-linear-to-r from-[oklch(0.55_0.25_270)] to-[oklch(0.75_0.15_195)] px-5 sm:px-6 py-2.5 text-sm font-semibold text-white shadow-[0_4px_24px_-4px_oklch(0.55_0.25_270/0.45),0_2px_16px_-4px_oklch(0.75_0.15_195/0.35)] transition-all duration-200 hover:shadow-[0_6px_32px_-4px_oklch(0.55_0.25_270/0.5),0_4px_20px_-4px_oklch(0.75_0.15_195/0.4)] hover:brightness-[1.06] active:scale-[0.98] active:brightness-100"
        >
          {t("nav.createAccount")}
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
      <Link
        href="/dashboard/account-settings"
        className="flex items-center gap-3.5 px-5 py-4 transition-colors hover:bg-(--surface-subtle)"
      >
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-black text-primary-foreground">
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[0.95rem] font-bold leading-tight text-(--foreground)">
            Hi, {user.name || "there"}
          </p>
          <p className="mt-0.5 truncate text-xs text-(--text-muted)">{user.email}</p>
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-(--text-muted)" />
      </Link>
      <button
        type="button"
        data-mobile-menu-close="true"
        onClick={async () => {
          await logout();
          router.push("/login");
        }}
        className="flex w-full items-center gap-3 px-5 py-3 text-sm font-bold text-(--text-soft) transition-colors hover:bg-(--surface-subtle) hover:text-(--foreground)"
      >
        <LogOut className="h-4 w-4 text-(--text-muted)" />
        Log Out
      </button>
    </>
  ) : null;

  const mobileActionContent = (
    <SignedOut>
      <div className="flex items-center justify-center gap-5 px-5 py-3">
        <Link
          href="/login"
          className={getHeaderUtilityLinkClassName()}
          data-mobile-menu-close="true"
        >
          {t("nav.login")}
        </Link>
        <Link
          href="/register"
          className={getHeaderUtilityLinkClassName()}
          data-mobile-menu-close="true"
        >
          {t("nav.createAccount")}
        </Link>
      </div>
    </SignedOut>
  );

  return (
    <>
      {/* Core-shell logical-property groundwork for RTL. Full physical→logical
          conversion across the app is a tracked follow-up. */}
      <header className="fixed inset-x-0 top-0 z-50">
        <div className="mt-4 px-4 sm:px-6 lg:px-8">
          <nav className="glass-card flex items-center justify-between gap-4 px-4 py-3 sm:px-6 sm:py-4">
            <Link
              href="/"
              aria-label="Qiko Signal home"
              className="group flex min-w-0 items-center"
            >
              <SignalBrandLockup
                size="auth"
                className="transition-transform duration-300 group-hover:scale-105"
              />
            </Link>
            <div className="hidden items-center gap-8 md:flex">
              <Link href={QIKO_HOME_URL} className={NAV_LINK_CLASS}>
                {t("nav.qiko", { defaultValue: "Home" })}
              </Link>
              <Link href={QIKO_LABS_URL} className={NAV_LINK_CLASS}>
                {t("nav.labs", { defaultValue: "Labs" })}
              </Link>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <Suspense
                fallback={
                  <div className="h-11 w-11 animate-pulse rounded-xl bg-white/5 md:hidden" />
                }
              >
                <MobileHeaderMenu
                  menuLabel={t("nav.openMenu", { defaultValue: "Open navigation menu" })}
                  userContent={mobileUserContent}
                  navContent={mobileNavContent}
                  actionContent={mobileActionContent}
                />
              </Suspense>
              <div className="hidden items-center gap-4 md:flex">{desktopActions}</div>
            </div>
          </nav>
        </div>
      </header>
      <div className="h-[88px] sm:h-[104px]" aria-hidden="true" />
    </>
  );
}
