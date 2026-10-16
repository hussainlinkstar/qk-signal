"use client";

import React, { useEffect } from "react";
import Link from "next/link";
import { ArrowLeft, Radio } from "lucide-react";

import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import { resolveQikoSiteUrl } from "@/lib/qiko-site-url";

const qikoSiteUrl = resolveQikoSiteUrl();

type AuthTenantBranding = {
  companyName?: string | null;
  customLogoUrl?: string | null;
  primaryColor?: string | null;
  secondaryColor?: string | null;
  customPageTitle?: string | null;
  customFaviconUrl?: string | null;
};

interface AuthShellProps {
  chipLabel: string;
  title: string;
  accentText?: string;
  subtitle?: string;
  footerText: string;
  footerCtaLabel: string;
  footerCtaHref: string;
  branding?: AuthTenantBranding | null;
  footerMeta?: React.ReactNode;
  children: React.ReactNode;
}

export default function AuthShell({
  chipLabel,
  title,
  accentText,
  subtitle,
  footerText,
  footerCtaLabel,
  footerCtaHref,
  branding,
  footerMeta,
  children,
}: AuthShellProps) {
  const primaryColor = branding?.primaryColor || "var(--purple)";
  const secondaryColor = branding?.secondaryColor || "var(--coral)";

  useEffect(() => {
    if (branding?.customPageTitle) {
      document.title = branding.customPageTitle;
    }
    if (!branding?.customFaviconUrl) {
      return;
    }
    let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = branding.customFaviconUrl;
  }, [branding?.customFaviconUrl, branding?.customPageTitle]);

  return (
    <main
      id="main-content"
      data-signal-theme
      data-signal-auth
      className="signal-canvas relative min-h-dvh font-(family-name:--body-font) text-(--t-1) antialiased"
      style={
        {
          "--auth-primary": primaryColor,
          "--auth-secondary": secondaryColor,
          "--auth-link": branding?.primaryColor || "var(--purple-deep)",
        } as React.CSSProperties
      }
    >
      <div className="mx-auto grid min-h-dvh w-full max-w-[1120px] lg:grid-cols-[1.05fr_0.95fr]">
        <aside className="signal-auth-brand relative hidden overflow-hidden px-10 py-12 lg:flex lg:flex-col lg:justify-between">
          <div className="relative z-10" aria-hidden="true">
            <span className="font-(family-name:--disp) text-[22px] font-extrabold tracking-[-0.02em] text-(--t-1)">
              {branding?.companyName || "Qiko Signal"}
            </span>
          </div>

          <div className="relative z-10 max-w-md space-y-5">
            <span className="signal-auth-chip inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-semibold tracking-wide">
              <Radio className="h-3.5 w-3.5" aria-hidden="true" />
              {chipLabel}
            </span>
            <h2 className="m-0 font-(family-name:--disp) text-[2.15rem] font-extrabold leading-[1.15] tracking-[-0.03em] text-(--t-1)">
              See how you show up in search and AI answers.
            </h2>
            <p className="signal-auth-muted m-0 text-[15px] leading-[1.55]">
              SEO, AEO, and GEO scores in one calm workspace — built for teams that ship fixes, not
              slide decks.
            </p>
            <ul className="signal-auth-muted m-0 flex list-none flex-col gap-2.5 p-0 text-[13.5px]">
              {[
                "Score bands that read at a glance",
                "Client-ready reports without the fluff",
                "Prompts, keywords, and competitors in one place",
              ].map((line) => (
                <li key={line} className="flex items-start gap-2.5">
                  <span className="signal-auth-dot mt-1.5 h-1.5 w-1.5 flex-none rounded-full" />
                  {line}
                </li>
              ))}
            </ul>
          </div>

          <p className="signal-auth-footer-note relative z-10 m-0 text-[12px]">
            Trusted visibility intelligence for modern search.
          </p>
        </aside>

        <div className="relative flex flex-col justify-center px-4 py-8 sm:px-8 sm:py-12 lg:px-12">
          <div className="mx-auto w-full max-w-[420px]">
            <Link
              href={qikoSiteUrl}
              className="mb-4 inline-flex min-h-11 items-center gap-[7px] rounded-(--r-sm) text-[13px] font-semibold text-(--t-2) transition-colors duration-150 hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--brand) lg:hidden"
            >
              <ArrowLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
              Back to home
            </Link>

            <div className="signal-auth-card overflow-hidden rounded-[24px] border border-(--line) bg-(--panel) p-6 sm:p-8">
              <div className="mb-5">
                <Link
                  href={qikoSiteUrl}
                  aria-label="Qiko home"
                  className="flex w-fit items-center gap-[6px] rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--brand)"
                >
                  {branding?.customLogoUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      alt={branding.companyName || "Workspace logo"}
                      className="h-[30px] max-w-[180px] object-contain"
                      src={branding.customLogoUrl}
                    />
                  ) : (
                    <SignalBrandLockup size="auth" />
                  )}
                </Link>
              </div>

              <div className="mb-1">
                <Link
                  href={qikoSiteUrl}
                  className="inline-flex min-h-9 items-center gap-[7px] rounded-(--r-sm) text-[13px] font-semibold text-(--t-2) transition-colors duration-150 hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--brand)"
                >
                  <ArrowLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
                  Back to home
                </Link>
              </div>

              <header className="mt-2">
                <h1 className="m-0 font-(family-name:--disp) text-[26px] font-extrabold leading-[1.2] tracking-[-0.02em] text-(--t-1)">
                  {title}
                  {accentText ? ` ${accentText}` : ""}
                </h1>
                {subtitle ? (
                  <p className="mt-2 text-[13.5px] leading-[1.5] text-(--t-2)">{subtitle}</p>
                ) : null}
              </header>

              <div className="mt-5">{children}</div>

              <div className="mt-5 border-t border-(--line-2) pt-4 text-center">
                <p className="text-[13px] leading-[1.5] text-(--t-2)">
                  {footerText}{" "}
                  <Link
                    href={footerCtaHref}
                    className="rounded-sm font-semibold text-(--auth-link) underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--brand)"
                  >
                    {footerCtaLabel}
                  </Link>
                </p>
                {footerMeta ? (
                  <div className="mt-3 text-[12px] leading-[1.5] text-(--t-3)">{footerMeta}</div>
                ) : null}
              </div>
            </div>

            <nav
              aria-label="Legal"
              className="mt-4 flex flex-wrap items-center justify-center gap-x-5 text-[12px] text-(--t-3)"
            >
              <Link
                href={`${qikoSiteUrl}/signal/terms`}
                className="inline-flex min-h-11 items-center rounded-sm transition-colors duration-150 hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand)"
              >
                Terms
              </Link>
              <Link
                href={`${qikoSiteUrl}/signal/privacy`}
                className="inline-flex min-h-11 items-center rounded-sm transition-colors duration-150 hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand)"
              >
                Privacy
              </Link>
              <Link
                href={`${qikoSiteUrl}/cookies`}
                className="inline-flex min-h-11 items-center rounded-sm transition-colors duration-150 hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand)"
              >
                Cookies
              </Link>
            </nav>
          </div>
        </div>
      </div>
    </main>
  );
}
