"use client";

import React from "react";

export default function ReportSection({
  eyebrow,
  title,
  anchorId,
  children,
}: {
  eyebrow?: string;
  title: string;
  /** Deep-link target, so a run result can link straight to this section. */
  anchorId?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={anchorId} className="scroll-mt-6 space-y-2">
      <div className="min-w-0 flex-1">
        {eyebrow ? (
          <div className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--purple)">
            {eyebrow}
          </div>
        ) : null}
        <div className="flex items-center gap-3">
          <h2 className="m-0 whitespace-normal! font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
            {title}
          </h2>
          <div className="h-px flex-1 bg-(--line)" aria-hidden />
        </div>
      </div>
      {children}
    </section>
  );
}
