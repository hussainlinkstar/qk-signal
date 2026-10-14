"use client";

import React from "react";
import Link from "next/link";
import { Activity, AlertTriangle } from "lucide-react";

import { useActiveAudits } from "@/hooks/useActiveAudits";
import { cx } from "@/components/ui/utils";

/**
 * Compact pulsing chip shown in the AppTopBar when one or more audits are
 * queued or running. Clicking it navigates to the audit workspace where the
 * user can re-attach to the running SSE stream.
 */
export default function ActiveAuditChip() {
  const { activeJobs, hasActiveAudits } = useActiveAudits();

  if (!hasActiveAudits) return null;

  const count = activeJobs.length;
  const anyStale = activeJobs.some((j) => j.stale);
  const firstJob = activeJobs[0];
  const label = firstJob.target_name || firstJob.target_url || firstJob.tier_display || "Audit";
  const shortLabel = label.length > 24 ? `${label.slice(0, 22)}...` : label;

  return (
    <Link
      href={`/dashboard/audit?reattach=${firstJob.job_id}`}
      className={cx(
        "inline-flex items-center gap-2 rounded border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest transition-colors",
        anyStale
          ? "border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20"
          : "border-primary/25 bg-primary/10 text-primary hover:bg-primary/20"
      )}
      title={count === 1 ? `${label}, ${firstJob.status}` : `${count} audits in progress`}
    >
      {anyStale ? (
        <AlertTriangle className="h-3.5 w-3.5" />
      ) : (
        <Activity className="h-3.5 w-3.5 animate-pulse" />
      )}
      <span className="hidden sm:inline">{count === 1 ? shortLabel : `${count} audits`}</span>
      <span className="sm:hidden">{count}</span>
    </Link>
  );
}
