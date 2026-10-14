"use client";

import Link from "next/link";
import type { ReactNode } from "react";

/**
 * signal-MVP `.crumb` (signal.css:77): a plain 13.5px inline row inside the
 * shared `.top` bar - parent links in --t-3, chevron separators, the current
 * page as a --disp bold leaf in --t-1. Registered by pages through
 * WorkspacePageHeaderContext so it renders inside SignalTopBar, never as a
 * second row underneath.
 */
export default function SignalCrumb({ items }: { items: { label: string; href?: string }[] }) {
  const sep = (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      className="h-[15px] w-[15px] rtl:-scale-x-100"
      strokeWidth={2}
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex min-w-0 items-center gap-2 text-[13.5px] text-(--t-3)"
    >
      {items.map((item, i) => {
        const last = i === items.length - 1;
        const node: ReactNode =
          last || !item.href ? (
            <b className="truncate font-(family-name:--disp) font-bold text-(--t-1)">
              {item.label}
            </b>
          ) : (
            <Link href={item.href} className="truncate text-(--t-3) hover:text-(--t-1)">
              {item.label}
            </Link>
          );
        return (
          <span key={i} className="flex min-w-0 items-center gap-2">
            {i > 0 ? sep : null}
            {node}
          </span>
        );
      })}
    </nav>
  );
}
