import type { ReactNode } from "react";
import { cx } from "@/components/ui/utils";

/**
 * signal.css `.skel` primitives (signal.css:899-912): quiet shimmer
 * placeholders shaped like the content they stand in for, while the app
 * shell stays visible. The `.skel` classes live in globals.css verbatim from
 * the approved stylesheet, including the RTL-reversed shimmer and the
 * prefers-reduced-motion branch.
 */
export function Skel({ className, children }: { className?: string; children?: ReactNode }) {
  return (
    <div aria-hidden="true" className={cx("skel", className)}>
      {children}
    </div>
  );
}

/** `.skel-line`: a 12px text-line placeholder. `w` picks the 40/60/80 variant. */
export function SkelLine({ w, className }: { w?: 40 | 60 | 80; className?: string }) {
  return (
    <div aria-hidden="true" className={cx("skel skel-line", w ? `w${w}` : undefined, className)} />
  );
}

/** `.skel-card`: a 120px card placeholder. */
export function SkelCard({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("skel skel-card", className)} />;
}

/** `.skel-circle`: a 40px avatar/icon placeholder. */
export function SkelCircle({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("skel skel-circle", className)} />;
}

/** `.skel-chart`: a 160px chart placeholder. */
export function SkelChart({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("skel skel-chart", className)} />;
}

/** `.dt-skelrow`: a table-row placeholder (flex 14px gap, 12/14 padding). */
export function SkelRow({ children, className }: { children?: ReactNode; className?: string }) {
  return <div className={cx("dt-skelrow", className)}>{children}</div>;
}

/**
 * Pagehead-shaped placeholder: a circle + two lines, matching the approved
 * `.pagehead` geometry (46px pico + title/subtitle).
 */
export function SkelPagehead() {
  return (
    <div role="status" className="flex items-center gap-3.5 py-2">
      <SkelCircle className="h-[46px] w-[46px] rounded-[13px]" />
      <div className="min-w-0 flex-1">
        <SkelLine w={40} />
        <SkelLine w={80} className="mb-0" />
      </div>
      <span className="sr-only">Loading</span>
    </div>
  );
}
