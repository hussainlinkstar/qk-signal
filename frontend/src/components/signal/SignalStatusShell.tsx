"use client";

import React, { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Cookie, Languages } from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import { useCookieConsent } from "@/contexts/CookieConsentContext";
import { RTL_ENABLED } from "@/lib/i18nFlags";
import { changeAppLanguage } from "@/components/LanguageSwitcher";
import SidebarWorkspaceMenu from "@/components/app/SidebarWorkspaceMenu";
import SignalAppShell, { type SignalNavSection } from "@/components/signal/SignalAppShell";
import SignalAppFooter from "@/components/signal/SignalAppFooter";
import SignalTopBar, { SIGNAL_SEARCH_INPUT_SELECTOR } from "@/components/signal/SignalTopBar";
import { toSignalNavSection } from "@/components/signal/mapNavSections";
import { workspaceNavSections } from "@/components/navigation/navigationConfig";

type SignalStatusShellProps = {
  /** The `.crumb` label the approved top bar shows on status pages. */
  crumb: string;
  /**
   * Page content. May be a render function receiving `openPalette` so the
   * page's own controls (the approved "Search everything" button) focus the
   * same quick-search field the top bar and ⌘K use.
   */
  children: React.ReactNode | ((openPalette: () => void) => React.ReactNode);
};

/**
 * The approved status-page layout (`data-page="maintenance"|"notfound"` in
 * signal-MVP): the full app shell — sidebar, top bar, footer — around a
 * single card. Everything here is static or degrades to the approved empty
 * state, so the page renders even when the API is down: the sidebar switcher
 * shows the generic workspace label and the nav is the static workspace IA.
 */
export default function SignalStatusShell({ crumb, children }: SignalStatusShellProps) {
  const { t } = useTranslation();
  const { logout, user } = useAuth();
  const { openSettings: openCookieSettings } = useCookieConsent();
  // The mock's only search surface is the inline `.tsearch` field: ⌘K and the
  // page-level "Search everything" button both just focus it.
  const openPalette = useCallback(() => {
    document.querySelector<HTMLElement>(SIGNAL_SEARCH_INPUT_SELECTOR)?.focus();
  }, []);

  const email = user?.email ?? "";

  const sections = useMemo(
    () =>
      workspaceNavSections.map((section) =>
        toSignalNavSection(section, t, { onLogout: () => void logout() })
      ),
    [logout, t]
  );

  const paletteSections = useMemo<SignalNavSection[]>(() => {
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
    return [...sections, { label: t("signalShell.actionsGroup"), items: actionItems }];
  }, [openCookieSettings, sections, t]);

  return (
    /* data-signal-status-shell: the (app) layout's AppTopBar hides itself
       via `.app-shell:has([data-signal-status-shell])` in globals.css so the
       approved single shell renders instead of two stacked top bars. */
    <div data-signal-status-shell>
      <SignalAppShell
        brandHref="/dashboard"
        brandName="Qiko"
        brandSub="Signal"
        topLink={{
          label: t("nav.workspaceOverview"),
          href: "/dashboard",
          icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <path d="M14 9l-3 3 3 3" />
            </svg>
          ),
        }}
        sections={sections}
        footerSlot={
          <SidebarWorkspaceMenu email={email} onLogout={() => void logout()} fetchEnabled={false} />
        }
      >
        <div className="relative flex min-h-[calc(100dvh-30px)] flex-col">
          <SignalTopBar siteLabel={crumb} searchSections={paletteSections} />
          {/* signal.css `.wrap`: padding 20px 32px 14px. */}
          <main className="flex flex-1 flex-col gap-[22px] px-8 pb-3.5 pt-5">
            {typeof children === "function" ? children(openPalette) : children}
          </main>
          <SignalAppFooter />
        </div>
      </SignalAppShell>
    </div>
  );
}
