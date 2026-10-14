"use client";

import React from "react";

import { cx } from "@/components/ui/utils";

/**
 * The `.card.sblock` shell every section of the approved start-scan page uses
 * (mockup: Signal Audit.html): panel surface, --line border, --r radius,
 * 20/22 padding, a `h3` title and the one-line `.sd` explanation underneath.
 *
 * Each section states what it is for in that sentence, which is why it is a
 * required prop rather than an optional extra.
 */
export default function AuditSection({
  id,
  heading,
  description,
  className,
  children,
}: {
  id?: string;
  heading: string;
  description: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <section
      id={id}
      aria-label={heading}
      className={cx("rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-5", className)}
    >
      <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold">{heading}</h3>
      <p className="m-0 mb-4 text-[12.5px] leading-[1.5] text-(--t-3)">{description}</p>
      {children}
    </section>
  );
}
