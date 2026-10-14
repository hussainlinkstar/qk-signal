"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { SignedIn, SignedOut } from "@/components/auth/custom-auth";
import { useTranslation } from "react-i18next";
import { ArrowUpRight } from "lucide-react";
import { useCookieConsent } from "@/contexts/CookieConsentContext";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import BrandLogo, { type BrandLogoId } from "@/components/ui/BrandLogo";
import { resolveQikoSiteUrl } from "@/lib/qiko-site-url";

// Signal is one of two products on the shared Qiko marketing site (qiko-website-v2); these link
// back to the sibling product's pages there. SIGNAL-1009.
const qikoSiteUrl = resolveQikoSiteUrl();
const QIKO_HOME_URL = qikoSiteUrl;
const QIKO_LABS_URL = `${qikoSiteUrl}/labs`;

type SocialLink = { platform: string; label: string; url: string };

const FALLBACK_SOCIAL_LINKS: SocialLink[] = [];

const SOCIAL_ICONS: Record<string, React.ReactNode> = {
  linkedin: (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  ),
  x: (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  ),
  youtube: (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
    </svg>
  ),
  facebook: (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
    </svg>
  ),
  instagram: (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 0C8.74 0 8.333.015 7.053.072 5.775.132 4.905.333 4.14.63c-.789.306-1.459.717-2.126 1.384S.935 3.35.63 4.14C.333 4.905.131 5.775.072 7.053.012 8.333 0 8.74 0 12s.015 3.667.072 4.947c.06 1.277.261 2.148.558 2.913.306.788.717 1.459 1.384 2.126.667.666 1.336 1.079 2.126 1.384.766.296 1.636.499 2.913.558C8.333 23.988 8.74 24 12 24s3.667-.015 4.947-.072c1.277-.06 2.148-.262 2.913-.558.788-.306 1.459-.718 2.126-1.384.666-.667 1.079-1.335 1.384-2.126.296-.765.499-1.636.558-2.913.06-1.28.072-1.687.072-4.947s-.015-3.667-.072-4.947c-.06-1.277-.262-2.149-.558-2.913-.306-.789-.718-1.459-1.384-2.126C21.319 1.347 20.651.935 19.86.63c-.765-.297-1.636-.499-2.913-.558C15.667.012 15.26 0 12 0zm0 2.16c3.203 0 3.585.016 4.85.071 1.17.055 1.805.249 2.227.415.562.217.96.477 1.382.896.419.42.679.819.896 1.381.164.422.36 1.057.413 2.227.057 1.266.07 1.646.07 4.85s-.015 3.585-.074 4.85c-.061 1.17-.256 1.805-.421 2.227-.224.562-.479.96-.899 1.382-.419.419-.824.679-1.38.896-.42.164-1.065.36-2.235.413-1.274.057-1.649.07-4.859.07-3.211 0-3.586-.015-4.859-.074-1.171-.061-1.816-.256-2.236-.421-.569-.224-.96-.479-1.379-.899-.421-.419-.69-.824-.9-1.38-.165-.42-.359-1.065-.42-2.235-.045-1.26-.061-1.649-.061-4.844 0-3.196.016-3.586.061-4.861.061-1.17.255-1.814.42-2.234.21-.57.479-.96.9-1.381.419-.419.81-.689 1.379-.898.42-.166 1.051-.361 2.221-.421 1.275-.045 1.65-.06 4.859-.06l.045.03zm0 3.678a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 1 0 0-12.324zM12 16c-2.21 0-4-1.79-4-4s1.79-4 4-4 4 1.79 4 4-1.79 4-4 4zm7.846-10.405a1.441 1.441 0 1 1-2.882 0 1.441 1.441 0 0 1 2.882 0z" />
    </svg>
  ),
  tiktok: (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z" />
    </svg>
  ),
};

const FooterLink = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <Link
    href={href}
    className="group flex items-center text-sm font-medium text-(--text-muted) transition-colors hover:text-(--foreground)"
  >
    {children}
    <ArrowUpRight className="ml-1 h-3 w-3 translate-x-1 -translate-y-1 opacity-0 text-primary transition-all group-hover:translate-x-0 group-hover:translate-y-0 group-hover:opacity-100" />
  </Link>
);

const FooterButton = ({
  children,
  onClick,
}: {
  children: React.ReactNode;
  onClick: () => void;
}) => (
  <button
    type="button"
    onClick={onClick}
    className="group flex items-center text-sm font-medium text-(--text-muted) transition-colors hover:text-(--foreground)"
  >
    {children}
    <ArrowUpRight className="ml-1 h-3 w-3 translate-x-1 -translate-y-1 opacity-0 text-primary transition-all group-hover:translate-x-0 group-hover:translate-y-0 group-hover:opacity-100" />
  </button>
);

const Footer = () => {
  const { t } = useTranslation();
  const { openSettings } = useCookieConsent();
  const [socialLinks, setSocialLinks] = useState<SocialLink[]>(FALLBACK_SOCIAL_LINKS);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/platform/social-links")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data?.links?.length) setSocialLinks(data.links);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const aiPartners = [
    {
      brand: "google_gemini",
      name: "Google Gemini",
      title: "Google Gemini model analysis",
      imageClassName: "h-8 w-8 sm:h-9 sm:w-9",
    },
    {
      brand: "openai",
      name: "OpenAI",
      title: "OpenAI model analysis",
      imageClassName: "h-7 w-7 invert sm:h-8 sm:w-8",
    },
    {
      brand: "anthropic",
      name: "Anthropic",
      title: "Anthropic model analysis",
      imageClassName: "h-7 w-7 invert sm:h-8 sm:w-8",
    },
    {
      brand: "xai",
      name: "Grok (xAI)",
      title: "Grok (xAI) model analysis",
      imageClassName: "h-7 w-7 sm:h-8 sm:w-8",
    },
    {
      brand: "deepseek",
      name: "DeepSeek",
      title: "DeepSeek model analysis",
      imageClassName: "h-7 w-7 sm:h-8 sm:w-8",
    },
  ] as const satisfies ReadonlyArray<{
    brand: BrandLogoId;
    name: string;
    title: string;
    imageClassName?: string;
  }>;

  return (
    <footer className="relative overflow-hidden border-t border-white/5 bg-(--background)">
      <div className="max-w-7xl mx-auto py-16 px-6 lg:px-8 relative z-10">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-12 lg:gap-8">
          <div className="col-span-2 md:col-span-2 pr-0 lg:pr-12">
            <Link href="/" aria-label="Qiko Signal home" className="group inline-flex max-w-full">
              <SignalBrandLockup
                size="auth"
                className="transition-transform duration-300 group-hover:scale-[1.02]"
              />
            </Link>
            <p className="mt-6 max-w-sm text-sm leading-relaxed text-(--text-muted)">
              {t("footer.tagline")}
            </p>
            <ul
              aria-label={t("signalEngines.modelsAria")}
              className="mt-8 flex flex-wrap items-center gap-5 sm:gap-6"
            >
              {aiPartners.map((partner) => (
                <li key={partner.name} className="flex items-center justify-center">
                  <BrandLogo
                    brand={partner.brand}
                    title={partner.title}
                    width={44}
                    height={44}
                    className="h-10 w-10 transition-transform duration-300 hover:scale-105 sm:h-11 sm:w-11"
                    imageClassName={partner.imageClassName ?? "h-7 w-7 sm:h-8 sm:w-8"}
                  />
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="mb-6 flex items-center gap-2 text-xs font-black uppercase tracking-[0.2em] text-(--foreground)">
              <span className="h-2 w-2 rounded-full bg-(--primary)" />
              {t("footer.product")}
            </h3>
            <ul className="space-y-4">
              <li>
                <SignedIn>
                  <FooterLink href="/dashboard">{t("nav.dashboard")}</FooterLink>
                </SignedIn>
                <SignedOut>
                  <FooterLink href="/login">{t("footer.signIn")}</FooterLink>
                </SignedOut>
              </li>
            </ul>
          </div>

          <div>
            <h3 className="mb-6 text-xs font-black uppercase tracking-[0.2em] text-(--foreground)">
              {t("footer.company")}
            </h3>
            <ul className="space-y-4">
              <li>
                <FooterLink href={QIKO_HOME_URL}>
                  {t("footer.qiko", { defaultValue: "Qiko" })}
                </FooterLink>
              </li>
              <li>
                <FooterLink href={QIKO_LABS_URL}>
                  {t("footer.labs", { defaultValue: "Qiko Labs" })}
                </FooterLink>
              </li>
            </ul>
          </div>

          <div>
            <h3 className="mb-6 text-xs font-black uppercase tracking-[0.2em] text-(--foreground)">
              {t("footer.legal")}
            </h3>
            <ul className="space-y-4">
              <li>
                <FooterLink href={`${qikoSiteUrl}/signal/privacy`}>
                  {t("footer.privacyPolicy")}
                </FooterLink>
              </li>
              <li>
                <FooterLink href={`${qikoSiteUrl}/signal/terms`}>{t("footer.terms")}</FooterLink>
              </li>
              <li>
                <FooterButton onClick={openSettings}>
                  {t("cookieConsent.footerAction", { defaultValue: "Cookie settings" })}
                </FooterButton>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-16 flex flex-col items-center justify-between gap-4 border-t border-(--border) pt-8 md:flex-row">
          <p className="text-sm font-medium text-(--text-muted)">
            {t("footer.copyright", { year: new Date().getFullYear() })}
          </p>
          <div className="flex items-center gap-5">
            {socialLinks.map((link) => (
              <a
                key={link.platform}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Qiko Signal on ${link.label}`}
                className="text-(--text-muted) transition-colors hover:text-(--foreground)"
              >
                {SOCIAL_ICONS[link.platform] ?? (
                  <span className="inline-flex h-5 w-5 items-center justify-center text-xs font-bold">
                    {link.label.slice(0, 2)}
                  </span>
                )}
              </a>
            ))}
            <span className="flex items-center gap-2 text-sm font-medium text-(--text-muted)">
              <span className="h-1.5 w-1.5 rounded-full bg-success shadow-[0_0_8px_rgba(22,163,74,0.28)]" />
              All Systems Operational
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
