"use client";

import Link from "next/link";
import { cx } from "@/components/ui/utils";

import AppLogo from "@/components/AppLogo";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";

/**
 * Minimal, presentation-only nav shape shared by both consumers of
 * SignalAppShell (dashboard + admin). Each caller maps its own nav config
 * (which use different icon/type shapes today — see navigationConfig.ts vs
 * admin/layout.tsx's local NavItem) into this shape; SignalAppShell itself
 * has no opinion on where nav data comes from or how it's filtered
 * (role/plan gating stays entirely in the caller).
 */
export type SignalNavItem = {
  name: string;
  href?: string;
  icon: React.ReactNode;
  badge?: string;
  disabled?: boolean;
  active?: boolean;
  /**
   * Non-navigating action item (the approved IA's "Sign out" entry). Rendered
   * as a button with nav-item styling; never as a link.
   */
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
  /**
   * The "Workspace overview" link the approved design pins under the brand,
   * above the nav sections (signal-MVP `.ws-link`). Rendered only when the
   * caller passes it; the workspace overview page omits its own self-link.
   */
  topLink?: { label: string; href: string; icon: React.ReactNode };
  sections: SignalNavSection[];
  /**
   * Single control rendered in the sidebar's bottom "foot" block. signal-MVP's
   * `.foot` holds exactly one `.ssw` switcher, so consumers pass one node here.
   */
  footerSlot?: React.ReactNode;
  shellClassName?: string;
  children: React.ReactNode;
};

// signal.css `.nav a`: gap 11px, height 30px (32px when `.on`), padding 0 10px,
// radius 9px, 14px/500; hover `--line-2`/`--t-1`; active `#EBEDFB`/`#3730A3`/600.
// The approved rows sit below the usual 44px touch guidance; that is the
// desktop-sidebar metric the design ships (the mobile drawer keeps 44px).
export const ITEM_CLASSES =
  "flex w-full items-center gap-[11px] rounded-[9px] px-2.5 text-start text-sm font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2 motion-reduce:transition-none";
export const ITEM_INACTIVE = "h-[30px] text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1)";
export const ITEM_ACTIVE = "h-8 bg-[#EBEDFB] font-semibold text-[#3730A3]";

function NavItemRow({ item }: { item: SignalNavItem }) {
  // signal.css `.nav a .soon`: mono 8.5px chip on `--paper`, pushed to the end.
  const badge = item.badge ? (
    <em className="ms-auto rounded-[4px] border border-(--line) bg-(--paper) px-[5px] py-[2px] font-(family-name:--mono) text-[8.5px] uppercase not-italic tracking-[0.08em] text-(--t-3)">
      {item.badge}
    </em>
  ) : null;
  const inner = (
    <>
      <span className="flex-none [&_svg]:h-[17px] [&_svg]:w-[17px] [&_svg]:stroke-[1.9]">
        {item.icon}
      </span>
      <span className="min-w-0 truncate leading-snug">{item.name}</span>
      {badge}
    </>
  );

  if (item.disabled && item.badge !== "Upgrade") {
    // SOON entries stay in the IA per the approved design but must announce
    // themselves as unavailable, not merely look grey. No role: an entry that
    // can neither be focused nor activated must not claim to be a link.
    return (
      <div
        aria-disabled="true"
        title={item.name}
        className="flex h-[30px] cursor-not-allowed items-center gap-[11px] rounded-[9px] px-2.5 text-sm font-medium text-(--t-3)"
      >
        {inner}
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
 * Shared sidebar + main-content shell for the signal-light design system.
 * Structure mirrors signal-MVP's `.app`/`.side`/`.nav`/`.foot` markup
 * (see signal-MVP signal.css): the whole app is a floating card inset 15px
 * from the viewport (max 1560px wide, `app float` shadow) on a #F2F4FB
 * canvas; the sidebar is a sticky 220px column with 16px rounded outer
 * corners, and `.main` takes the trailing corners. No collapse affordance
 * (signal-MVP has none; mobile handling lands in a later phase, desktop
 * sidebar is `hidden lg:flex` in the meantime).
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
  return (
    <div
      data-testid="signal-app-shell"
      data-signal-theme
      className={cx(
        "min-h-dvh w-full text-(--t-1) font-(family-name:--body-font) leading-[normal]",
        shellClassName
      )}
      // The canvas behind the floating app card is the mockup's body colour;
      // inline style wins over [data-signal-theme]'s own --paper background.
      style={{ background: "var(--signal-canvas)" }}
    >
      <div className="mx-auto my-[15px] flex min-h-[calc(100dvh-30px)] w-[calc(100%-30px)] max-w-[1560px] shadow-[0_1px_3px_rgba(15,23,42,0.07),0_8px_24px_rgba(15,23,42,0.05)]">
        {/* signal.css `.side`: 220px, padding 20px 10px, sticky top 15,
            height 100dvh-30, panel bg, inline-end border, leading corners. */}
        <aside className="hidden w-[220px] flex-none flex-col rounded-s-[16px] border-e border-(--line) bg-(--panel) px-2.5 py-5 sticky top-[15px] h-[calc(100dvh-30px)] lg:flex">
          {/* `.brand`: logo mark (h21) + "Signal" sig, bottom --line-2 rule. */}
          <Link
            href={brandHref}
            aria-label={brandName}
            className="flex items-center gap-[9px] rounded-none border-b border-(--line-2) px-2.5 pb-[13px] pt-1 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2"
          >
            {brandSub ? (
              <SignalBrandLockup word={brandSub} />
            ) : (
              <AppLogo className="flex-none" iconClassName="h-[21px] w-auto flex-none" />
            )}
          </Link>

          {topLink ? (
            /* `.ws-link`: 13.5px/600 #4F46E5, gap 8, bottom --line-2 rule. */
            <Link
              href={topLink.href}
              className="flex items-center gap-2 border-b border-(--line-2) px-2.5 pb-[13px] pt-2.5 text-[13.5px] font-semibold text-[#4F46E5] transition-colors hover:text-[#4338CA] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2 motion-reduce:transition-none"
            >
              <span className="flex-none [&_svg]:h-[15px] [&_svg]:w-[15px] [&_svg]:stroke-2">
                {topLink.icon}
              </span>
              <span className="min-w-0 truncate leading-snug">{topLink.label}</span>
            </Link>
          ) : null}

          {/* `.nav`: no inter-row gap; `.lab` gets a top rule + extra space
              on every label but the first. */}
          <nav
            aria-label="Main navigation"
            className="min-h-0 flex-1 overflow-y-auto flex flex-col"
          >
            {sections.map((section, index) => (
              <div key={section.label}>
                <div
                  className={cx(
                    "px-2.5 pb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.12em] text-(--t-3)",
                    index === 0 ? "pt-[11px]" : "mt-2 border-t border-(--line-2) pt-4"
                  )}
                >
                  {section.label}
                </div>
                {section.items.map((item) => (
                  <NavItemRow key={item.href ?? item.name} item={item} />
                ))}
              </div>
            ))}
          </nav>

          {/* `.side .foot`: margin-top auto, padding-top 12px, no top rule. */}
          {footerSlot ? <div className="mt-auto flex-none pt-3">{footerSlot}</div> : null}
        </aside>

        {/* `.main`: paper bg, trailing corners. */}
        <div className="min-w-0 flex-1 rounded-e-[16px] bg-(--paper)">{children}</div>
      </div>
    </div>
  );
}
