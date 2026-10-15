"use client";

import React, { useEffect } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

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
  chipLabel: _chipLabel,
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
  const primaryColor = branding?.primaryColor || "var(--blue)";
  const secondaryColor = branding?.secondaryColor || "var(--purple)";

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
      className="signal-canvas relative flex min-h-dvh items-center justify-center px-4 py-8 font-(family-name:--body-font) text-(--t-1) antialiased sm:py-12"
      style={
        {
          "--auth-primary": primaryColor,
          "--auth-secondary": secondaryColor,
          "--auth-link": branding?.primaryColor || "var(--brand)",
        } as React.CSSProperties
      }
    >
      <div className="w-full max-w-[400px]">
        <Link
          href={qikoSiteUrl}
          className="mb-3 inline-flex min-h-11 items-center gap-[7px] rounded-(--r-sm) text-[13px] font-semibold text-(--t-2) transition-colors duration-150 hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--brand)"
        >
          <ArrowLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          Back to home
        </Link>

        <div className="rounded-[22px] border-0 bg-white p-6">
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

          <header>
            <h1 className="m-0 font-(family-name:--disp) text-[24px] font-extrabold leading-[1.25] tracking-[-0.02em] text-(--t-1)">
              {title}
              {accentText ? ` ${accentText}` : ""}
            </h1>
            {subtitle ? (
              <p className="mt-2 text-[13.5px] leading-[1.5] text-(--t-2)">{subtitle}</p>
            ) : null}
          </header>

          <div className="mt-[18px]">{children}</div>

          <div className="mt-[18px] border-t border-(--line-2) pt-4 text-center">
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
          className="mt-3 flex flex-wrap items-center justify-center gap-x-5 text-[12px] text-(--t-3)"
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
    </main>
  );
}
