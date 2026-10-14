import React from "react";
import { ChevronRight, Boxes, FileText, Link2, RefreshCw } from "lucide-react";

import { cx } from "@/components/ui/utils";
import GatedSection from "@/components/results/GatedSection";
import { getPlanLockContent } from "@/lib/planLocks";

type ExecutionPanelProps = {
  /**
   * When `true`, the panel preview is blurred behind a `GatedSection` upsell
   * (done-for-you execution is gated to Executive+). Defaults to `true`
   * (fail-safe LOCKED) so the panel never renders unlocked unless a caller
   * explicitly grants the capability.
   */
  isLocked?: boolean;
  /** Optional guest-audit token forwarded to the gated upsell CTA. */
  guestAuditToken?: string;
  className?: string;
};

type ExecutionItem = {
  id: string;
  title: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
};

const EXECUTION_ITEMS: ExecutionItem[] = [
  {
    id: "schema",
    title: "Schema & structured data",
    detail: "We implement the missing structured data so AI engines parse your entities cleanly.",
    icon: Boxes,
  },
  {
    id: "content",
    title: "Content fixes",
    detail: "We rewrite and ship the priority on-page content changes from your action plan.",
    icon: FileText,
  },
  {
    id: "link-reclaim",
    title: "Link reclaim",
    detail: "We recover lost mentions and reclaim broken or unlinked references to your brand.",
    icon: Link2,
  },
  {
    id: "monthly-loop",
    title: "Monthly execution loop",
    detail: "Your top fixes are implemented every month on a continuous improve-and-measure loop.",
    icon: RefreshCw,
  },
];

const ExecutionPanelBody = () => (
  <div className="space-y-6" data-testid="execution-panel">
    <div className="space-y-1">
      <h3 className="flex items-center gap-3 text-sm font-black uppercase tracking-[0.2em] text-(--t-1)">
        <ChevronRight className="h-4 w-4 text-primary" />
        Done for you
      </h3>
      <p className="pl-7 text-xs font-medium text-(--t-3)">
        We implement your top fixes (schema, content, link reclaim) on a monthly execution loop.
      </p>
    </div>
    <ul className="space-y-3">
      {EXECUTION_ITEMS.map(({ id, title, detail, icon: Icon }) => (
        <li
          key={id}
          className="relative flex gap-4 rounded border border-(--line) bg-(--line-2) p-4 shadow-inner transition-colors hover:bg-(--line-2)"
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-primary/[0.08] text-primary">
            <Icon className="h-3.5 w-3.5" />
          </div>
          <div className="flex-1 space-y-1">
            <p className="text-sm font-semibold leading-snug text-(--t-1)">{title}</p>
            <p className="text-xs leading-relaxed text-(--t-2)">{detail}</p>
          </div>
        </li>
      ))}
    </ul>
  </div>
);

/**
 * Presentational "done-for-you execution" summary panel.
 *
 * Describes the Executive-tier service where Qiko Signal implements the top
 * fixes (schema, content, link reclaim) on a continuous monthly loop. When
 * `isLocked` is `true` (the fail-safe default), the panel is shown blurred
 * behind the existing `GatedSection` upsell keyed to the Executive plan; the
 * lock copy is sourced from the shared `doneForYouExecution` plan-lock content.
 */
export default function ExecutionPanel({
  isLocked = true,
  guestAuditToken,
  className,
}: ExecutionPanelProps) {
  if (isLocked) {
    const lock = getPlanLockContent("doneForYouExecution");
    return (
      <div className={cx(className)}>
        <GatedSection
          title="Done for you"
          teaser={lock.description}
          requiredPlan="executive"
          requiredPlanLabel={lock.requiredPlanLabel}
          guestAuditToken={guestAuditToken}
          blurredPreview={<ExecutionPanelBody />}
          features={[
            "Schema and priority content fixes shipped for you",
            "Lost or broken brand mentions reclaimed",
            "Continuous monthly improve-and-measure loop",
          ]}
        />
      </div>
    );
  }

  return (
    <div className={cx(className)}>
      <ExecutionPanelBody />
    </div>
  );
}
