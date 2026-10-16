"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React from "react";
import { Loader2 } from "lucide-react";

import SignalMetricStrip from "@/components/signal/SignalMetricStrip";
import { GlassCard } from "@/components/ui/GlassComponents";
import Button from "@/components/ui/Button";
import type { WorkspaceCostBreakdown, WorkspaceProjectSummary } from "@/services/workspaceService";

type WorkspaceCostBreakdownSectionProps = {
  breakdown: WorkspaceCostBreakdown | null;
  projects: WorkspaceProjectSummary[];
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
};

function stripDomainProtocol(value: string | null): string {
  return value ? value.replace(/^https?:\/\//i, "").replace(/\/$/, "") : "Pending domain";
}

export function WorkspaceCostBreakdownSection({
  breakdown,
  projects,
  isLoading,
  error,
  onRetry,
}: WorkspaceCostBreakdownSectionProps) {
  const rows = breakdown?.projects ?? [];
  const budgetsConfigured = rows.filter((row) => row.budget_configured).length;
  const exhaustedCount = rows.filter((row) => row.status === "exhausted").length;
  const warningCount = rows.filter((row) => row.status === "warning").length;
  const attention = warningCount + exhaustedCount;

  return (
    <GlassCard className="rounded-(--r) border-(--line) bg-(--panel) px-[22px] py-[18px]">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h3 className="text-[15px] font-bold text-(--t-1)">Project Cost Breakdown</h3>
          <p className="mt-1 max-w-3xl text-[12.5px] leading-6 text-(--t-2)">
            Review current-period spend across every project. Unlimited projects still show usage so
            finance and delivery teams can spot concentration risk early.
          </p>
        </div>

        <SignalMetricStrip
          className="w-full lg:max-w-[420px]"
          items={[
            { label: "Projects", value: rows.length },
            { label: "Caps Active", value: budgetsConfigured },
            {
              label: "Attention",
              value: attention,
              tone: attention > 0 ? "warn" : "default",
            },
          ]}
        />
      </div>

      {isLoading ? (
        <div className="mt-6 flex min-h-[180px] flex-col items-center justify-center gap-3 rounded-[14px] border border-(--line) bg-white">
          <Loader2 className="h-6 w-6 animate-spin text-(--purple)" />
          <p className="text-[12.5px] font-medium text-(--t-2)">Loading cost breakdown</p>
        </div>
      ) : error ? (
        <SignalAlert
          tone="danger"
          title="Cost breakdown unavailable"
          className="mt-6"
          actions={
            <Button variant="ghost" onClick={onRetry} className="h-9 px-4">
              Retry Load
            </Button>
          }
        >
          {error}
        </SignalAlert>
      ) : projects.length === 0 ? (
        <div className="mt-6 rounded-[14px] border border-dashed border-(--line) bg-white p-5 text-[12.5px] text-(--t-2)">
          Create at least one workspace project before you can track project-level budget usage.
        </div>
      ) : rows.length === 0 ? (
        <div className="mt-6 rounded-[14px] border border-dashed border-(--line) bg-white p-5 text-[12.5px] text-(--t-2)">
          No cost breakdown data is available yet.
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          {budgetsConfigured === 0 ? (
            <div className="rounded-[14px] border border-(--line) bg-(--purple-s) px-4 py-3.5 text-[12.5px] leading-6 text-(--t-2)">
              No project caps are configured yet. You can still review spend by project and enable
              hard guardrails from each project&apos;s settings page.
            </div>
          ) : null}

          <div className="overflow-x-auto rounded-[14px] border border-(--line) bg-white">
            <table className="w-full min-w-[560px] border-collapse text-left">
              <thead>
                <tr className="border-b border-(--line)">
                  <th className="px-4 py-3 text-[12px] font-semibold text-(--t-2)">Project</th>
                  <th className="px-4 py-3 text-[12px] font-semibold text-(--t-2)">Cap</th>
                  <th className="px-4 py-3 text-[12px] font-semibold text-(--t-2)">Spent</th>
                  <th className="px-4 py-3 text-[12px] font-semibold text-(--t-2)">Remaining</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.project_id} className="border-b border-(--line-2) last:border-0">
                    <td className="px-4 py-3.5">
                      <p className="text-[13.5px] font-semibold text-(--t-1)">{row.project_name}</p>
                      <p className="mt-0.5 text-[12px] text-(--t-3)">
                        {stripDomainProtocol(row.domain_url)}
                      </p>
                    </td>
                    <td className="px-4 py-3.5 text-[13px] tabular-nums text-(--t-1)">
                      {row.monthly_limit_scans === null ? (
                        <span className="inline-flex rounded-full bg-(--purple-s) px-2.5 py-0.5 text-[11px] font-semibold text-(--purple-deep,var(--purple))">
                          Unlimited
                        </span>
                      ) : (
                        row.monthly_limit_scans.toLocaleString()
                      )}
                    </td>
                    <td className="px-4 py-3.5 font-(family-name:--mono) text-[13px] tabular-nums text-(--t-1)">
                      {row.consumed_scans.toLocaleString()}
                    </td>
                    <td className="px-4 py-3.5 text-[13px] tabular-nums text-(--t-1)">
                      {row.remaining_scans === null
                        ? "Unlimited"
                        : row.remaining_scans.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </GlassCard>
  );
}
