"use client";

import React, { useId, useState } from "react";

import { cx } from "@/components/ui/utils";

/**
 * One expandable report section, on the approved disclosure anatomy
 * (SIGV2-1317).
 *
 * The reference is Scan history in `Signal Overview.html:482`, the only
 * expandable section in the approved design:
 *
 *   .scan-history           { /* .card *\/ overflow:hidden }
 *   .scan-history-heading   { display:flex; align-items:center; gap:16px;
 *                             padding:20px 22px; cursor:pointer }
 *   .scan-history-heading>div { flex:1; min-width:0 }
 *   .scan-history-heading h2  { font:700 17px var(--disp); margin:0 0 5px }
 *   .scan-history-heading p   { font-size:12px; line-height:1.65;
 *                               color:var(--t-2) }
 *   .history-count          { font:11px var(--mono); color:var(--t-2) }
 *   .history-chevron        { font-size:22px; color:var(--t-2) }
 *   [open] .history-chevron { transform:rotate(45deg) }
 *   .history-content        { border-top:1px solid var(--line);
 *                             padding:16px 22px }
 *
 * Three things change here, and each was a real defect.
 *
 * **The disclosure is the card.** It used to be a row inside a shared panel
 * that wrapped every section, while each section's content wrapped itself
 * again, so the page was three cards deep where the design is one. That is
 * the nesting the page was reported for.
 *
 * **The body shares the heading's left edge.** It was `padding-left: 74px`
 * against a heading at 22px, so no two things on the page lined up
 * vertically. 74 matches nothing in the approved design; it reads like an
 * icon-plus-gap measurement borrowed from another layout. The approved body
 * is `16px 22px` under a `1px solid var(--line)` rule.
 *
 * **The chevron is the approved `+` turning 45 degrees**, not a caret turning
 * 90. Same glyph, same size and same colour as Scan history, so a customer
 * meets one expand control in this product rather than two.
 */
export default function ReportDisclosure({
  title,
  description,
  anchorId,
  meta,
  defaultOpen = false,
  children,
}: {
  title: string;
  description?: string;
  anchorId?: string;
  /** Approved `.history-count` slot: a short count or state, never a control. */
  meta?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

  return (
    <section
      id={anchorId}
      className="scroll-mt-6 overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)"
    >
      <button
        type="button"
        className="flex w-full cursor-pointer items-center gap-4 border-0 bg-transparent px-[22px] py-3 text-start hover:bg-(--line-2)"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="min-w-0 flex-1">
          <span className="block font-(family-name:--disp) text-[17px] font-bold leading-[1.25] tracking-[-0.01em] text-(--t-1)">
            {title}
          </span>
          {description ? (
            <span className="mt-[5px] block text-[12px] leading-[1.65] text-(--t-2)">
              {description}
            </span>
          ) : null}
        </span>
        {meta ? (
          <span className="whitespace-nowrap font-(family-name:--mono) text-[11px] text-(--t-2)">
            {meta}
          </span>
        ) : null}
        <span
          aria-hidden="true"
          className={cx(
            "text-[22px] leading-none text-(--t-2) transition-transform",
            open && "rotate-45"
          )}
        >
          +
        </span>
      </button>
      <div
        id={bodyId}
        className={cx(
          "border-t border-t-(--line) px-[22px] py-4 [&_p]:m-0! [&_p]:text-[13px] [&_p]:leading-[1.55] [&_p]:text-(--t-2) [&_ul]:mt-1.5! [&_ul]:mb-0! [&_ul]:list-none [&_ul]:pl-0",
          !open && "hidden"
        )}
      >
        {children}
      </div>
    </section>
  );
}
