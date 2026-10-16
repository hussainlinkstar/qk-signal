import { Skel, SkelCard, SkelPagehead, SkelRow } from "@/components/signal/SignalSkeleton";

type DashboardPageSkeletonProps = {
  /** Number of large card placeholders under the pagehead. */
  cards?: number;
  /** Show a tab-row shaped bar (account / billing style). */
  showTabs?: boolean;
};

/**
 * Shared page-level loading shape used by workspace settings, account, billing,
 * etc. — shimmer skeletons instead of spinner + “Loading…” copy.
 */
export default function DashboardPageSkeleton({
  cards = 2,
  showTabs = false,
}: DashboardPageSkeletonProps) {
  return (
    <div role="status" className="flex flex-col gap-[18px]">
      <SkelPagehead />
      {showTabs ? <Skel className="h-[42px] w-full max-w-[420px] rounded-[14px]" /> : null}
      <Skel className="h-[34px] w-[280px] rounded-[9px]" />
      {Array.from({ length: cards }).map((_, index) => (
        <SkelCard key={index} className={index === 0 ? "h-[220px]" : "h-[160px]"} />
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

/** Compact table-body placeholder for invoice / list refreshes. */
export function DashboardTableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div role="status" className="px-4 py-3" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <SkelRow key={index} className="border-0 px-0">
          <div aria-hidden="true" className="skel h-3.5 w-[28%] rounded-(--r-sm)" />
          <div aria-hidden="true" className="skel h-3.5 w-[18%] rounded-(--r-sm)" />
          <div aria-hidden="true" className="skel h-3.5 w-[16%] rounded-(--r-sm)" />
          <div aria-hidden="true" className="skel ms-auto h-3.5 w-[22%] rounded-(--r-sm)" />
        </SkelRow>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}
