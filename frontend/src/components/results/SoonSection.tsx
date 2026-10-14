"use client";

import React, { useEffect, useRef } from "react";

import { cx } from "@/components/ui/utils";

/**
 * The "not built yet" treatment, deliberately NOT the plan-upsell treatment.
 *
 * `GatedSection` (and the `.lockwrap.locked` markup in signal-mvp.css) blurs a
 * section that exists and that money unlocks: it carries a Lock icon, a plan
 * name and an upgrade button. A section that simply does not exist yet must
 * never borrow that language, otherwise someone pays for a feature that is not
 * there. So this component shows no lock, no plan, no price and no button, and
 * reuses the one marker the product already uses for unbuilt modules: the
 * bordered mono SOON chip from the sidebar (`navigationConfig.soon`,
 * `SidebarSection` NavBadge) and its CSS twin `.chipE.soon em`.
 *
 * Everything below the overlay is decoration only. It is blurred, faded,
 * `pointer-events-none`, `aria-hidden`, `inert`, and any focusable descendant
 * is stamped with `tabindex="-1"`, so the surface cannot be clicked, tabbed
 * into, or read out as if it were real data.
 */

/**
 * React 18 has no typed `inert` prop and warns on a boolean value, so the
 * attribute is spread in as the empty string HTML expects. Browsers that
 * support `inert` then remove the subtree from hit testing and the tab order
 * outright; the class names and the tabindex sweep below cover the rest.
 */
const INERT_ATTRIBUTE = {
  inert: Number.parseInt(React.version, 10) >= 19 ? true : "",
} as unknown as React.HTMLAttributes<HTMLDivElement>;

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button",
  "input",
  "select",
  "textarea",
  "iframe",
  "audio[controls]",
  "video[controls]",
  "summary",
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function SoonBadge({ className }: { className?: string }) {
  return (
    <em
      className={cx(
        "rounded-[5px] border border-(--line) px-[5px] py-px font-(family-name:--mono) text-[9px] not-italic uppercase tracking-[0.08em] text-(--t-3)",
        className
      )}
    >
      SOON
    </em>
  );
}

function NeutralPreview() {
  // Shapes only, never plausible numbers: a fake metric read through a blur
  // still reads as data the product has.
  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="h-5 w-2/5 rounded-full bg-(--line-2)" />
      <div className="h-3 w-4/5 rounded-full bg-(--line-2)" />
      <div className="h-3 w-3/5 rounded-full bg-(--line-2)" />
      <div className="h-3 w-2/3 rounded-full bg-(--line-2)" />
    </div>
  );
}

export type SoonSectionProps = {
  /**
   * What is coming. Not rendered as a heading (call sites already have one),
   * it names the region for screen readers: "Keywords, coming soon".
   */
  title: string;
  /** One short plain-English line. No jargon, no CTA, no plan, no price. */
  note?: string;
  /** Optional decorative preview. Falls back to a neutral placeholder. */
  preview?: React.ReactNode;
  className?: string;
};

const DEFAULT_NOTE = "We are still building this. It will show up here once it is ready.";

export default function SoonSection({
  title,
  note = DEFAULT_NOTE,
  preview,
  className,
}: SoonSectionProps) {
  const previewRef = useRef<HTMLDivElement | null>(null);

  // `inert` is not implemented in jsdom and is missing in older browsers, so
  // keyboard reachability is closed off directly as well: a caller-supplied
  // preview can contain anything, including a button that was interactive
  // before it became decoration.
  useEffect(() => {
    const node = previewRef.current;
    if (!node) return;
    node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR).forEach((element) => {
      element.setAttribute("tabindex", "-1");
    });
  });

  return (
    <section
      aria-label={`${title}, coming soon`}
      data-testid="soon-section"
      className={cx(
        "relative isolate min-h-[168px] overflow-hidden rounded-xl border border-dashed border-(--line) bg-(--panel)",
        className
      )}
    >
      <div
        ref={previewRef}
        aria-hidden="true"
        tabIndex={-1}
        data-testid="soon-section-preview"
        {...INERT_ATTRIBUTE}
        className="pointer-events-none select-none opacity-40 blur-[6px]"
      >
        {preview ?? <NeutralPreview />}
      </div>

      {/* Not a button, not a link, and pointer-events-none so the whole
          surface stays dead rather than swallowing clicks into a dead end. */}
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2.5 px-6 text-center">
        <SoonBadge />
        <p className="max-w-[46ch] text-[13px] leading-5 text-(--t-2)">{note}</p>
      </div>
    </section>
  );
}
