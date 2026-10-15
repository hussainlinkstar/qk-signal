"use client";

import React from "react";

import { cx } from "@/components/ui/utils";

/**
 * The one card shell every settings section uses, so the page reads as an
 * ordered list of short, plainly named blocks instead of thirteen bespoke
 * layouts.
 */
export type SettingsSectionProps = {
  id?: string;
  eyebrow?: string;
  title: string;
  description?: React.ReactNode;
  aside?: React.ReactNode;
  tone?: "default" | "danger";
  /** sblock (Product tab): 20/22 padding, 14.5px title. wsec (Brand tab):
      18/22 padding, 15px title, matching the approved .wsec cards. */
  variant?: "sblock" | "wsec";
  className?: string;
  children?: React.ReactNode;
};

export default function SettingsSection({
  id,
  eyebrow,
  title,
  description,
  aside,
  tone = "default",
  variant = "sblock",
  className,
  children,
}: SettingsSectionProps) {
  const danger = tone === "danger";
  const wsec = variant === "wsec";
  return (
    <section
      id={id}
      tabIndex={id ? -1 : undefined}
      className={cx(
        "rounded-[22px] border-0 bg-white px-[22px]",
        wsec ? "py-[18px]" : "py-5",
        danger && "border-[color-mix(in_srgb,var(--bad)_40%,transparent)]",
        className
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && (
            <p
              className={cx(
                "m-0 text-[11px] uppercase tracking-[0.14em]",
                danger ? "text-(--bad)" : "text-(--t-3)"
              )}
            >
              {eyebrow}
            </p>
          )}
          <h3
            className={cx(
              "font-(family-name:--disp) font-bold tracking-[-0.01em]",
              wsec ? "text-[15px]" : "text-[14.5px]",
              danger ? "text-(--bad)" : undefined,
              eyebrow ? "mt-1.5" : "m-0"
            )}
          >
            {title}
          </h3>
          {description && (
            <p className="mt-1 text-[12.5px] leading-[1.5] text-(--t-3)">{description}</p>
          )}
        </div>
        {aside && <div className="flex flex-none items-center gap-3">{aside}</div>}
      </div>
      {children && <div className="mt-4">{children}</div>}
    </section>
  );
}
