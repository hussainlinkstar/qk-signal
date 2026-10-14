"use client";

import React from "react";
import {
  CARD_CONTAINER_PRESETS,
  CARD_SUBSECTION_SURFACE_CLASS,
} from "@/components/ui/cardStyleTokens";
import { GlassCard } from "@/components/ui/GlassComponents";
import { TYPO } from "@/components/ui/typographyTokens";
import { cx } from "@/components/ui/utils";

type BrandStudioPanelProps = {
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
};

export function BrandStudioPanel({
  eyebrow,
  title,
  description,
  actions,
  className,
  children,
}: BrandStudioPanelProps) {
  return (
    <GlassCard className={cx(CARD_CONTAINER_PRESETS.primary, "space-y-6", className)}>
      <div className="flex flex-col gap-4 border-b border-(--border) pb-6 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <p className={TYPO.microLabel}>{eyebrow}</p>
          <h3 className={TYPO.sectionTitle}>{title}</h3>
          <p className="max-w-3xl text-sm leading-7 text-(--muted-foreground)">{description}</p>
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
      {children}
    </GlassCard>
  );
}

type BrandStudioMetricCardProps = {
  label: string;
  value: string;
  detail: string;
  accentClassName?: string;
};

export function BrandStudioMetricCard({
  label,
  value,
  detail,
  accentClassName = "border-brand-aeo/40 bg-brand-aeo/10",
}: BrandStudioMetricCardProps) {
  return (
    <div className={cx(CARD_SUBSECTION_SURFACE_CLASS, "space-y-3", accentClassName)}>
      <p className={TYPO.microLabel}>{label}</p>
      <p className="wrap-break-word text-lg font-semibold tracking-tight text-(--foreground)">
        {value}
      </p>
      <p className="text-sm leading-6 text-(--muted-foreground)">{detail}</p>
    </div>
  );
}

type BrandStudioChecklistProps = {
  eyebrow: string;
  title: string;
  items: string[];
  className?: string;
};

export function BrandStudioChecklist({
  eyebrow,
  title,
  items,
  className,
}: BrandStudioChecklistProps) {
  return (
    <GlassCard className={cx(CARD_CONTAINER_PRESETS.secondary, "space-y-4", className)}>
      <div className="space-y-2">
        <p className={TYPO.microLabel}>{eyebrow}</p>
        <h4 className={TYPO.cardTitle}>{title}</h4>
      </div>
      <div className="space-y-3">
        {items.map((item, index) => (
          <div key={`${index}-${item}`} className="flex items-start gap-3">
            <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-brand-aeo/40 bg-brand-aeo/10 text-[11px] font-semibold text-brand-aeo">
              {index + 1}
            </div>
            <p className="text-sm leading-6 text-(--muted-foreground)">{item}</p>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

type BrandSurfacePreviewProps = {
  eyebrow: string;
  surfaceLabel: string;
  brandName: string;
  title: string;
  description: string;
  subtitle?: string | null;
  logoUrl?: string | null;
  primaryColor: string;
  secondaryColor: string;
  hidePoweredBy?: boolean;
  footerLinks?: string[];
  companyName?: string | null;
  companyAddress?: string | null;
  companyTrademarkText?: string | null;
  socialIcons?: Array<{
    label: string;
    iconSrc: string;
  }>;
  className?: string;
};

export function BrandSurfacePreview({
  eyebrow,
  surfaceLabel,
  brandName,
  title,
  description,
  subtitle,
  logoUrl,
  primaryColor,
  secondaryColor,
  hidePoweredBy = false,
  footerLinks = [],
  companyName,
  companyAddress,
  companyTrademarkText,
  socialIcons = [],
  className,
}: BrandSurfacePreviewProps) {
  const resolvedBrandName = brandName.trim() || "Agency Brand";
  const resolvedTitle = title.trim() || resolvedBrandName;
  const resolvedDescription =
    description.trim() || "Preview the current branded shell before saving it.";
  const initials = resolvedBrandName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((chunk) => chunk[0])
    .join("")
    .toUpperCase();

  return (
    <div className={cx("space-y-4", className)}>
      <div className="space-y-2">
        <p className={TYPO.microLabel}>{eyebrow}</p>
        <h4 className={TYPO.cardTitle}>Experience preview</h4>
      </div>

      <div
        className="overflow-hidden rounded border border-(--border) bg-(--panel)"
        style={
          {
            "--preview-primary": primaryColor,
            "--preview-secondary": secondaryColor,
            boxShadow: `0 32px 60px -40px ${primaryColor}`,
          } as React.CSSProperties
        }
      >
        <div className="border-b border-(--line) bg-(--surface) px-5 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              {logoUrl ? (
                <div className="flex h-11 items-center rounded border border-(--line) bg-white px-3">
                  {/* Local preview images use blob/data URLs and do not benefit from next/image here. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={logoUrl}
                    alt={resolvedBrandName}
                    className="h-6 w-auto max-w-[140px] object-contain"
                  />
                </div>
              ) : (
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded text-sm font-semibold text-[#09090B] bg-(--preview-primary)">
                  {initials || "BR"}
                </div>
              )}

              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-(--foreground)">
                  {resolvedBrandName}
                </p>
                <p className="truncate text-xs text-(--t-2)">
                  {subtitle?.trim() || "custom.domain.com"}
                </p>
              </div>
            </div>

            {!hidePoweredBy ? (
              <span className="text-[10px] font-medium uppercase tracking-wider text-(--t-3)">
                Powered by Qiko Signal
              </span>
            ) : null}
          </div>
        </div>

        <div className="space-y-4 px-5 py-5">
          <div className="rounded border border-(--line) bg-(--line-2) p-4">
            <p className={TYPO.microLabel}>{surfaceLabel}</p>
            <p className="mt-2 text-base font-semibold text-(--foreground)">{resolvedTitle}</p>
            <p className="mt-2 text-sm leading-6 text-(--muted-foreground)">
              {resolvedDescription}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded border border-(--line) bg-(--line-2) p-4">
              <p className={TYPO.microLabel}>Primary accent</p>
              <div className="mt-3 h-14 rounded border border-(--line) bg-(--preview-primary)" />
            </div>
            <div className="rounded border border-(--line) bg-(--line-2) p-4">
              <p className={TYPO.microLabel}>Secondary accent</p>
              <div className="mt-3 h-14 rounded border border-(--line) bg-(--preview-secondary)" />
            </div>
          </div>

          {footerLinks.length ||
          socialIcons.length ||
          companyName ||
          companyAddress ||
          companyTrademarkText ? (
            <div className="rounded border border-(--line) bg-(--line-2) p-4">
              <p className={TYPO.microLabel}>Delivery footer</p>

              {socialIcons.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {socialIcons.map((item) => (
                    <span
                      key={item.label}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 bg-white"
                      title={item.label}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={item.iconSrc} alt={item.label} className="h-4 w-4" />
                    </span>
                  ))}
                </div>
              ) : null}

              {companyName || companyAddress || companyTrademarkText ? (
                <div className="mt-4 border-t border-(--line) pt-3 text-xs text-(--t-2)">
                  <p>{companyName || resolvedBrandName}</p>
                  {companyAddress ? (
                    <p className="mt-1 whitespace-pre-line text-(--t-2)">{companyAddress}</p>
                  ) : null}
                  {companyTrademarkText ? (
                    <p className="mt-2 text-[11px] text-(--t-3)">{companyTrademarkText}</p>
                  ) : null}
                </div>
              ) : null}

              {footerLinks.length ? (
                <div className="mt-3 flex flex-wrap gap-3 text-[11px] font-medium text-brand-aeo">
                  {footerLinks.map((item) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
