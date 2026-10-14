"use client";

import React, { useCallback, useId, useRef, useState } from "react";

import { cx } from "@/components/ui/utils";

export type SignalXSellRow = { label: string; value: string; negative?: boolean };

type SignalXSellProps = {
  /** `.xs-head` - the metric name. */
  head: string;
  /** `.xs-q` - direction-derived question line. */
  question: string;
  /** `.xs-p` - honest provenance line. */
  body: string;
  rows: SignalXSellRow[];
  children: React.ReactNode;
};

const WIDTH = 296;
const GAP = 12;

/**
 * signal-MVP `.xsell-overlay` (app.js QXsell): a 296px dark card that reveals
 * on hover of the KPI, positioned fixed below or above the trigger so it
 * stays fully in the viewport and never covers it. Keyboard parity added on
 * top of the mock's hover-only behaviour: the card is focusable, focus/blur
 * toggles the overlay and Escape dismisses it.
 */
export default function SignalXSell({ head, question, body, rows, children }: SignalXSellProps) {
  const id = useId().replace(/:/g, "");
  const overlayId = `xsell-${id}`;
  const cardRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  const [below, setBelow] = useState(true);

  const place = useCallback(() => {
    const card = cardRef.current;
    const overlay = overlayRef.current;
    if (!card || !overlay) return;
    const r = card.getBoundingClientRect();
    const w = overlay.offsetWidth || WIDTH;
    const h = overlay.offsetHeight || 300;
    const below = r.bottom + GAP + h <= window.innerHeight - 8;
    const top = below ? r.bottom + GAP : r.top - GAP - h;
    const left = Math.min(Math.max(r.left + r.width / 2 - w / 2, 8), window.innerWidth - w - 8);
    overlay.style.top = `${Math.max(top, 8)}px`;
    overlay.style.left = `${left}px`;
    overlay.style.setProperty(
      "--cx",
      `${Math.max(10, Math.min(w - 24, r.left + r.width / 2 - left - 7))}px`
    );
    setBelow(below);
  }, []);

  const show = useCallback(() => {
    setShown(true);
    // Placement needs the rendered box, so measure after the frame commits.
    requestAnimationFrame(place);
  }, [place]);
  const hide = useCallback(() => setShown(false), []);

  // Keep the card glued to its trigger while it is open.
  React.useEffect(() => {
    if (!shown) return;
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [shown, place]);

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- keyboard
    // access to the overlay is required; Escape dismisses, blur hides.
    <div
      ref={cardRef}
      tabIndex={0}
      aria-describedby={overlayId}
      className="focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          hide();
          (e.currentTarget as HTMLElement).blur();
        }
      }}
    >
      {children}
      <div
        ref={overlayRef}
        id={overlayId}
        role="tooltip"
        className={cx(
          "pointer-events-none fixed z-30 w-[296px] rounded-[14px] bg-[#11151F] px-[18px] pb-[10px] pt-4 text-[12px] leading-[1.5] text-[#E8EBF2] shadow-[0_24px_60px_-18px_rgba(12,15,22,0.45)] transition-[opacity,transform,visibility] duration-180 ease-out motion-reduce:transition-none",
          shown ? "visible translate-y-0 opacity-100" : "invisible translate-y-[6px] opacity-0"
        )}
      >
        {/* `.xsell-overlay::before`: 14px rotated square anchored at --cx,
            above the card's top edge when below the trigger (xs-down),
            at the bottom edge when flipped (xs-up). */}
        <span
          aria-hidden="true"
          className={cx(
            "absolute h-[14px] w-[14px] rotate-45 rounded-[2px] bg-[#11151F] [inset-inline-start:var(--cx,30px)]",
            below ? "-top-[7px]" : "-bottom-[7px]"
          )}
        />
        <div className="mb-2.5 border-b border-white/12 pb-2.5 font-(family-name:--disp) text-[13.5px] font-bold text-white">
          {head}
        </div>
        <div className="mb-[3px] font-(family-name:--disp) text-[13px] font-bold text-white">
          {question}
        </div>
        <div className="mb-3 text-[rgba(232,235,242,0.55)]">{body}</div>
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex items-center justify-between border-t border-white/8 py-[7px]"
          >
            <span className="font-medium text-[rgba(232,235,242,0.85)]">{row.label}</span>
            <b
              className={cx(
                "font-(family-name:--mono) text-[11px] font-medium",
                row.negative ? "text-[#F87171]" : "text-[#34D399]"
              )}
            >
              {row.value}
            </b>
          </div>
        ))}
      </div>
    </div>
  );
}
