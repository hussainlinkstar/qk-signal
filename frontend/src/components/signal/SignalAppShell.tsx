"use client";

import Link from "next/link";
import { cx } from "@/components/ui/utils";

import AppLogo from "@/components/AppLogo";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";

/**
 * Minimal, presentation-only nav shape shared by both consumers of
 * SignalAppShell (dashboard + admin). Gating stays in the caller.
 */
export type SignalNavItem = {
  name: string;
  href?: string;
  icon: React.ReactNode;
  badge?: string;
  disabled?: boolean;
  active?: boolean;
  onSelect?: () => void;
};

export type SignalNavSection = {
  label: string;
  items: SignalNavItem[];
};

export type SignalAppShellProps = {
  brandHref: string;
  brandName: string;
  brandSub?: string;
  topLink?: { label: string; href: string; icon: React.ReactNode };
  sections: SignalNavSection[];
  /** Profile / workspace switcher — flat block under brand. */
  footerSlot?: React.ReactNode;
  shellClassName?: string;
  children: React.ReactNode;
};

// Soft tinted icon tiles cycle — CashPilot metric-icon language.
const ICON_TILES = [
  { bg: "bg-[#E8F1FF]", fg: "text-[#3B82F6]" },
  { bg: "bg-[#FFE8F1]", fg: "text-[#EC4899]" },
  { bg: "bg-[#E7F9EF]", fg: "text-[#22C55E]" },
  { bg: "bg-[#FFF3E0]", fg: "text-[#F59E0B]" },
  { bg: "bg-[#F3E8FF]", fg: "text-[#8B5CF6]" },
  { bg: "bg-[#E0F7FA]", fg: "text-[#06B6D4]" },
] as const;

export const ITEM_CLASSES =
  "group flex w-full items-center gap-3 rounded-full px-2.5 text-start text-[14px] font-medium transition-colors duration-200 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[#111827] focus-visible:ring-offset-2 motion-reduce:transition-none";
export const ITEM_INACTIVE = "h-11 text-[#4B5563] hover:bg-[#F3F4F6] hover:text-[#111827]";
export const ITEM_ACTIVE = "h-11 bg-[#E8F1FF] font-semibold text-[#1D4ED8] shadow-none";

function NavBadge({ label }: { label: string }) {
  const numeric = /^\d+$/.test(label.trim());
  if (numeric) {
    return (
      <em className="ms-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-[#111827] px-1.5 text-[10px] font-bold not-italic text-white">
        {label}
      </em>
    );
  }
  return (
    <em className="ms-auto rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[9px] font-semibold uppercase not-italic tracking-[0.06em] text-[#9CA3AF]">
      {label}
    </em>
  );
}

function NavItemRow({ item, tileIndex }: { item: SignalNavItem; tileIndex: number }) {
  const tile = ICON_TILES[tileIndex % ICON_TILES.length];
  const badge = item.badge ? <NavBadge label={item.badge} /> : null;
  const iconWrap = (
    <span
      className={cx(
        "flex h-8 w-8 flex-none items-center justify-center rounded-[10px] [&_svg]:h-[17px] [&_svg]:w-[17px] [&_svg]:stroke-[1.8]",
        tile.bg,
        tile.fg
      )}
    >
      {item.icon}
    </span>
  );
  const inner = (
    <>
      {iconWrap}
      <span className="min-w-0 truncate leading-snug">{item.name}</span>
      {badge}
    </>
  );

  if (item.disabled && item.badge !== "Upgrade") {
    return (
      <div
        aria-disabled="true"
        title={item.name}
        className="flex h-11 cursor-not-allowed items-center gap-3 rounded-full px-2.5 text-[14px] font-medium text-[#9CA3AF]"
      >
        <span className="flex h-8 w-8 flex-none items-center justify-center rounded-[10px] bg-[#F3F4F6] text-[#9CA3AF] [&_svg]:h-[17px] [&_svg]:w-[17px]">
          {item.icon}
        </span>
        <span className="min-w-0 truncate">{item.name}</span>
        {badge}
      </div>
    );
  }

  if (item.onSelect) {
    return (
      <button
        type="button"
        onClick={item.onSelect}
        data-signal-nav-item
        className={cx(ITEM_CLASSES, ITEM_INACTIVE)}
      >
        {inner}
      </button>
    );
  }

  return (
    <Link
      href={item.href ?? "#"}
      aria-current={item.active ? "page" : undefined}
      data-signal-nav-item
      className={cx(ITEM_CLASSES, item.active ? ITEM_ACTIVE : ITEM_INACTIVE)}
    >
      {inner}
    </Link>
  );
}

/**
 * CashPilot-inspired shell: one flat app frame on a soft stage.
 * Sidebar/header are plain regions — not separate floating cards.
 */
export default function SignalAppShell({
  brandHref,
  brandName,
  brandSub = "Signal",
  topLink,
  sections,
  footerSlot,
  shellClassName,
  children,
}: SignalAppShellProps) {
  let tileCursor = 0;

  return (
    <div
      data-testid="signal-app-shell"
      data-signal-theme
      className={cx(
        "min-h-dvh w-full bg-[#F3F4F6] text-(--t-1) font-(family-name:--body-font) leading-[normal]",
        shellClassName
      )}
    >
      <div className="mx-auto my-3 flex min-h-[calc(100dvh-1.5rem)] w-[calc(100%-1.5rem)] max-w-[1600px] overflow-hidden rounded-[28px] bg-[#F7F8FA] shadow-[0_20px_50px_-28px_rgba(15,23,42,0.28)] lg:my-4 lg:min-h-[calc(100dvh-2rem)] lg:w-[calc(100%-2rem)]">
        <aside className="sticky top-0 hidden h-[calc(100dvh-2rem)] w-[248px] flex-none flex-col bg-transparent px-4 py-5 lg:flex">
          <Link
            href={brandHref}
            aria-label={brandName}
            className="mb-5 flex items-center gap-2 px-1 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[#111827] focus-visible:ring-offset-2"
          >
            {brandSub ? (
              <SignalBrandLockup word={brandSub} />
            ) : (
              <AppLogo className="flex-none" iconClassName="h-[21px] w-auto flex-none" />
            )}
          </Link>

          {/* Flat welcome / workspace switcher — not a card */}
          {footerSlot ? <div className="mb-5 px-1">{footerSlot}</div> : null}

          {topLink ? (
            <Link
              href={topLink.href}
              className="mb-3 flex items-center gap-3 rounded-full px-2.5 py-2.5 text-[13.5px] font-medium text-[#4B5563] transition-colors hover:bg-[#F3F4F6] hover:text-[#111827] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[#111827] focus-visible:ring-offset-2"
            >
              <span className="flex h-8 w-8 flex-none items-center justify-center rounded-[10px] bg-[#E8F1FF] text-[#3B82F6] [&_svg]:h-4 [&_svg]:w-4 [&_svg]:stroke-[1.8]">
                {topLink.icon}
              </span>
              <span className="min-w-0 truncate">{topLink.label}</span>
            </Link>
          ) : null}

          <nav
            aria-label="Main navigation"
            className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:thin]"
          >
            {sections.map((section, index) => (
              <div key={section.label} className={cx(index === 0 ? "" : "mt-6")}>
                <div className="px-2.5 pb-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#9CA3AF]">
                  {section.label}
                </div>
                <div className="flex flex-col gap-1">
                  {section.items.map((item) => {
                    const tileIndex = tileCursor++;
                    return (
                      <NavItemRow key={item.href ?? item.name} item={item} tileIndex={tileIndex} />
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
        </aside>

        <div className="relative min-w-0 flex-1 bg-[#F7F8FA]">{children}</div>
      </div>
    </div>
  );
}
