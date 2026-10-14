"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";

import { getNavItemClassName } from "@/components/navigation/navItemStyles";
import type { NavSection } from "@/components/navigation/navigationConfig";
import {
  isRouteActive,
  resolveNavBadge,
  resolveNavLabel,
  resolveNavName,
} from "@/components/navigation/navigationConfig";
import { cx } from "@/components/ui/utils";

/**
 * signal-MVP nav badge (app.js `SOON`): bordered mono chip, not a warning pill.
 * Same treatment as the desktop sidebar in SignalAppShell.
 */
function NavBadge({ label }: { label: string }) {
  return (
    <em className="ms-auto rounded-[5px] border border-(--line) px-[5px] py-px font-(family-name:--mono) text-[9px] not-italic tracking-[0.08em] text-(--t-3)">
      {label}
    </em>
  );
}

type SidebarSectionProps = {
  section: NavSection;
  pathname: string;
  collapsed?: boolean;
  tone?: "primary" | "danger";
  className?: string;
  /** Start closed? Default = false (open) */
  defaultOpen?: boolean;
  /** Handler for `action` nav items (e.g. the approved IA's "Sign out"). */
  onAction?: (action: NonNullable<NavSection["items"][number]["action"]>) => void;
};

export default function SidebarSection({
  section,
  pathname,
  collapsed = false,
  tone = "primary",
  className,
  defaultOpen = true,
  onAction,
}: SidebarSectionProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const itemName = (item: NavSection["items"][number]) => resolveNavName(item, t);
  const itemHref = (item: NavSection["items"][number]) => item.href ?? "";
  const itemActive = (item: NavSection["items"][number]) =>
    item.href ? isRouteActive(pathname, item.href) : false;

  // Any item in this section active? → keep section open
  const hasActiveItem = section.items.some(itemActive);

  // Effective open state: forced open if section contains active route
  const effectiveOpen = isOpen || hasActiveItem;

  // Collapsed sidebar → no labels, no toggle, just icons
  if (collapsed) {
    return (
      <section className={cx("space-y-1", className)}>
        {section.items.map((item) => {
          const Icon = item.icon;
          const active = itemActive(item);
          if (item.disabled || !item.href) {
            return (
              <div
                key={item.href ?? item.name}
                className="flex w-full cursor-not-allowed items-center justify-center rounded-xl px-2 py-3 text-(--t-3)"
                title={itemName(item)}
                {...(item.disabled ? { "aria-disabled": true } : {})}
              >
                <Icon size={20} strokeWidth={2} />
              </div>
            );
          }
          return (
            <Link
              key={item.href}
              href={item.href}
              title={itemName(item)}
              className={cx(getNavItemClassName({ active, tone }), "justify-center px-2")}
            >
              <Icon size={20} strokeWidth={2} className="shrink-0" />
            </Link>
          );
        })}
      </section>
    );
  }

  return (
    <section className={cx("space-y-0.5", className)}>
      {/* Section toggle header */}
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-start transition-colors hover:text-(--t-1)"
        aria-expanded={effectiveOpen}
      >
        <span className="flex-1 font-(family-name:--mono) text-[10px] uppercase tracking-[0.12em] text-(--t-3) transition-colors group-hover:text-(--t-2)">
          {resolveNavLabel(section, t)}
        </span>
        <ChevronDown
          size={12}
          className={cx(
            "shrink-0 text-(--t-3) transition-transform duration-200",
            effectiveOpen && "rotate-180"
          )}
        />
      </button>

      {/* Items */}
      {effectiveOpen && (
        <div className="space-y-0.5">
          {section.items.map((item) => {
            const Icon = item.icon;
            const active = itemActive(item);
            const badge = resolveNavBadge(item, t);

            if (item.disabled && badge !== "Upgrade") {
              // SOON entries stay visible per the approved design but announce
              // themselves as unavailable to assistive technology. No role:
              // an entry that cannot be activated must not claim to be a link.
              return (
                <div
                  key={item.href ?? item.name}
                  aria-disabled="true"
                  className="flex w-full cursor-not-allowed items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-(--t-3)"
                  title={itemName(item)}
                >
                  <Icon size={18} strokeWidth={2} className="shrink-0" />
                  <span className="min-w-0 wrap-break-word leading-snug">{itemName(item)}</span>
                  {badge ? <NavBadge label={badge} /> : null}
                </div>
              );
            }

            if (item.action) {
              return (
                <button
                  key={item.name}
                  type="button"
                  onClick={() => onAction?.(item.action!)}
                  className={getNavItemClassName({ active: false, tone })}
                >
                  <Icon size={18} strokeWidth={2} className="shrink-0" />
                  <span className="min-w-0 wrap-break-word leading-snug">{itemName(item)}</span>
                  {badge ? <NavBadge label={badge} /> : null}
                </button>
              );
            }

            return (
              <Link
                key={itemHref(item)}
                href={itemHref(item)}
                className={getNavItemClassName({ active, tone })}
              >
                <Icon size={18} strokeWidth={2} className="shrink-0" />
                <span className="min-w-0 wrap-break-word leading-snug">{itemName(item)}</span>
                {badge ? <NavBadge label={badge} /> : null}
              </Link>
            );
          })}
        </div>
      )}
    </section>
  );
}
