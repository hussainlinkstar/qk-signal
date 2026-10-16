"use client";

import React, { useState } from "react";
import { ChevronDown } from "lucide-react";

import { cx } from "@/components/ui/utils";

/**
 * Start-scan section shell — white panel on the lilac canvas with a
 * colorful top rail (not the old flat grey card stack).
 */
export default function AuditSection({
  id,
  heading,
  description,
  className,
  children,
  collapsible = false,
  defaultOpen = true,
  summary,
}: {
  id?: string;
  heading: string;
  description: string;
  className?: string;
  children?: React.ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  /** One-line summary shown when collapsed. */
  summary?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const showBody = !collapsible || open;

  return (
    <section
      id={id}
      aria-label={heading}
      className={cx(
        "relative overflow-hidden rounded-[22px] border border-(--line) bg-white px-6 py-6 shadow-[var(--card-shadow,0_4px_24px_-8px_rgba(88,28,135,0.1))]",
        className
      )}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[3px]"
        style={{
          background:
            "linear-gradient(90deg, var(--purple) 0%, var(--coral, #f97316) 48%, var(--mint, #14b8a6) 100%)",
        }}
      />
      {collapsible ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-start gap-3 text-left"
        >
          <div className="min-w-0 flex-1">
            <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold">
              {heading}
            </h3>
            <p className="m-0 text-[12.5px] leading-[1.5] text-(--t-3)">
              {open ? description : summary || description}
            </p>
          </div>
          <span className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full bg-(--purple-s) text-(--purple-deep,var(--purple))">
            <ChevronDown
              className={cx(
                "h-4 w-4 transition-transform duration-200",
                open && "rotate-180"
              )}
              aria-hidden="true"
            />
          </span>
        </button>
      ) : (
        <>
          <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold">
            {heading}
          </h3>
          <p className="m-0 mb-4 text-[12.5px] leading-[1.5] text-(--t-3)">{description}</p>
        </>
      )}
      {showBody ? <div className={cx(collapsible && "mt-4")}>{children}</div> : null}
    </section>
  );
}
