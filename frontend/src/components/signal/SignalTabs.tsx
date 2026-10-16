"use client";

import React, { useEffect, useRef } from "react";

import { SoonBadge } from "@/components/results/SoonSection";
import { cn } from "@/components/ui/utils";

export type SignalTab<T extends string = string> = {
  id: T;
  label: string;
  count?: number;
  /**
   * The panel behind this tab is not built yet. This is a label only: it puts
   * the same SOON chip the sidebar uses on unbuilt modules onto the tab, so a
   * user knows before clicking, and it changes nothing else. The tab stays
   * selectable and keyboard-reachable on purpose, because the panel carries
   * the blurred, inert SOON treatment (see `SoonSection`) and disabling the
   * tab would hide the very message the user needs to see. This is not a plan
   * gate: nothing here can be unlocked by paying.
   */
  soon?: boolean;
};

export type SignalTabsProps<T extends string = string> = {
  tabs: SignalTab<T>[];
  activeId: T;
  onChange: (id: T) => void;
  className?: string;
};

const tabId = (id: string) => `signal-tab-${id}`;
const panelId = (id: string) => `signal-tabpanel-${id}`;

/**
 * Segmented pill control. Purely presentational, panel visibility is the
 * caller's responsibility (see SignalTabPanel).
 *
 * This used to be an underline bar (container `border-b`, each tab
 * `border-b-2 -mb-px`), which collided with the global
 * `button:not(.rounded-full) { border-radius: var(--r-md) }` rule: every tab
 * picked up a 10px radius, so its 2px underline curved up at both ends and the
 * row read as a set of unfinished, clipped boxes. Pills want a radius, and
 * `rounded-full` is the documented opt-out from that global rule, so the two
 * stop fighting instead of one overriding the other.
 */
export default function SignalTabs<T extends string>({
  tabs,
  activeId,
  onChange,
  className,
}: SignalTabsProps<T>) {
  const tabRefs = useRef(new Map<T, HTMLButtonElement>());

  useEffect(() => {
    const activeTab = tabRefs.current.get(activeId);
    if (typeof activeTab?.scrollIntoView === "function") {
      activeTab.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }, [activeId]);

  const selectTab = (id: T, focus = false) => {
    onChange(id);
    const tab = tabRefs.current.get(id);
    if (focus) tab?.focus();
  };

  // A SOON tab is navigated exactly like any other: it has a panel, and that
  // panel is where the "coming soon" message lives.
  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    const direction = event.currentTarget.closest<HTMLElement>("[dir]")?.dir === "rtl" ? -1 : 1;
    if (event.key === "ArrowLeft") nextIndex = (index - direction + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") nextIndex = (index + direction + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(tabs[nextIndex].id, true);
  };

  return (
    <div
      role="tablist"
      className={cn(
        // Vertical spacing comes from the parent flex gap — extra mt/mb here
        // stacked with page gaps and left a blank band under the score hero.
        "flex w-full max-w-full gap-1.5 overflow-x-auto rounded-[16px] bg-(--well,#EEF1F6) p-1.5",
        className
      )}
    >
      {tabs.map((tab, index) => {
        const soon = tab.soon === true;
        const active = tab.id === activeId;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              if (node) tabRefs.current.set(tab.id, node);
              else tabRefs.current.delete(tab.id);
            }}
            id={tabId(tab.id)}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={panelId(tab.id)}
            tabIndex={active ? 0 : -1}
            onClick={() => selectTab(tab.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={cn(
              "inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-full px-4 py-2.5 font-(family-name:--body-font) text-[13.5px] font-semibold leading-[normal] transition-colors duration-150",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)",
              active
                ? "bg-white text-(--purple-deep,var(--purple)) shadow-sm"
                : "bg-transparent text-(--t-3) hover:bg-white/70 hover:text-(--t-1)"
            )}
          >
            {tab.label}
            {soon && <SoonBadge />}
            {tab.count !== undefined && (
              <span
                className={cn(
                  "rounded-full px-1.5 py-px font-(family-name:--mono) text-[11px] font-normal tabular-nums",
                  active
                    ? "bg-(--purple-s) text-(--purple-deep,var(--purple))"
                    : "bg-white text-(--t-3)"
                )}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function SignalTabPanel<T extends string>({
  id,
  activeId,
  children,
  className,
}: {
  id: T;
  activeId: T;
  children: React.ReactNode;
  className?: string;
}) {
  if (id !== activeId) return null;
  return (
    <div
      id={panelId(id)}
      role="tabpanel"
      aria-labelledby={tabId(id)}
      tabIndex={0}
      // signal-MVP `.panelw.on` stacks a panel's cards with a 16px gap. Callers
      // used to get no spacing at all unless they passed their own, which left
      // sibling cards touching, so the MVP gap is the default here.
      className={cn("flex flex-col gap-4", className)}
    >
      {children}
    </div>
  );
}
