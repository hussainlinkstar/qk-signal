"use client";

import { useTranslation } from "react-i18next";
import { useCookieConsent } from "@/contexts/CookieConsentContext";

import AppLogo from "@/components/AppLogo";
import { resolveQikoSiteUrl } from "@/lib/qiko-site-url";

const qikoSiteUrl = resolveQikoSiteUrl();

const FOOTER_LINKS = [
  { key: "footer.linkTerms", href: `${qikoSiteUrl}/signal/terms` },
  { key: "footer.linkPrivacy", href: `${qikoSiteUrl}/signal/privacy` },
  { key: "footer.linkCookies", href: `${qikoSiteUrl}/cookies` },
] as const;

/**
 * signal-MVP `.site-footer` (mountFooter): the slim page footer the approved
 * design pins after `<main>` — qiko logo + copyright on one side, Terms /
 * Privacy / Cookies / Cookie settings on the other. The consent control calls
 * the shared `useCookieConsent().openSettings`; the marketing `Footer`
 * component is a different surface and is not reused here. `mt-auto` keeps it
 * at the bottom of the column without hiding real content overflow.
 */
export default function SignalAppFooter() {
  const { t } = useTranslation();
  const { openSettings } = useCookieConsent();

  // `.site-footer`: border-top --line, padding 6px 32px; `.footer-inner`
  // centres brand and links with the approved min(24vw,340px) gap.
  return (
    <footer className="mt-auto flex-none border-t border-transparent px-2 py-3">
      <div className="flex flex-wrap items-center justify-center gap-x-[min(24vw,340px)] gap-y-2">
        <div className="flex items-center gap-2.5">
          {/* The centred row keeps the outgoing logo's 44.75px slot width so
              the narrower wordmark does not shift the copyright and links.
              This row renders the Qiko mark, not the product wordmark: the
              1.38MB SVG wrapper whose paint-time downscale used to jitter here
              is gone from the codebase entirely (SIGV2-1087). */}
          <AppLogo className="flex-none" iconClassName="h-[18px] w-auto" priority />
          <span className="text-[12.5px] text-(--t-3)">
            {t("footer.copyrightLine", { year: new Date().getFullYear() })}
          </span>
        </div>
        <nav aria-label={t("footer.legal")} className="flex flex-wrap items-center gap-5">
          {FOOTER_LINKS.map((link) => (
            <a
              key={link.key}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[12.5px] font-medium text-(--t-3) transition-colors hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
            >
              {t(link.key)}
            </a>
          ))}
          <button
            type="button"
            onClick={openSettings}
            className="text-[12.5px] font-medium text-(--t-3) transition-colors hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
          >
            {t("footer.cookieSettings")}
          </button>
        </nav>
      </div>
    </footer>
  );
}
