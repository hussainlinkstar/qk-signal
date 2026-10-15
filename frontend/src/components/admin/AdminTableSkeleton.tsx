import React from "react";
import { SkelCard, SkelRow } from "@/components/signal/SignalSkeleton";

interface AdminTableSkeletonProps {
  rows?: number;
  columns?: number;
  className?: string;
}

/**
 * Table skeleton loader for admin pages, built on the MVP `.skel` shimmer.
 * Approximates the shape of a `.dtable`: a header bar plus body rows.
 */
export function AdminTableSkeleton({
  rows = 5,
  columns = 4,
  className = "",
}: AdminTableSkeletonProps) {
  return (
    <div
      className={`overflow-hidden rounded-(--r-md) border-0 bg-white ${className}`}
    >
      {/* Header row */}
      <div className="flex items-center gap-3.5 border-b border-(--line) px-3.5 py-3">
        {Array.from({ length: columns }).map((_, j) => (
          <div key={`h-${j}`} aria-hidden="true" className="skel h-3 flex-1 rounded-(--r-sm)" />
        ))}
      </div>

      {/* Body rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <SkelRow key={`r-${i}`}>
          {Array.from({ length: columns }).map((_, j) => (
            <div
              key={`r-${i}-c-${j}`}
              aria-hidden="true"
              className="skel h-3.5 rounded-(--r-sm)"
              style={{
                width:
                  j === 0
                    ? `${30 + Math.abs(Math.sin(i * 1.5)) * 20}%`
                    : `${15 + Math.abs(Math.cos(i * 0.7 + j)) * 10}%`,
              }}
            />
          ))}
        </SkelRow>
      ))}
    </div>
  );
}

interface AdminCardSkeletonProps {
  cards?: number;
  className?: string;
}

/**
 * Card skeleton loader for admin stat grids.
 */
export function AdminCardSkeleton({ cards = 4, className = "" }: AdminCardSkeletonProps) {
  const mdCols = ["md:grid-cols-1", "md:grid-cols-2", "md:grid-cols-3", "md:grid-cols-4"][
    Math.min(Math.max(cards, 1), 4) - 1
  ];
  return (
    <div className={`grid grid-cols-2 gap-4 ${mdCols} ${className}`}>
      {Array.from({ length: cards }).map((_, i) => (
        <SkelCard key={`card-${i}`} className="h-[88px]" />
      ))}
    </div>
  );
}
