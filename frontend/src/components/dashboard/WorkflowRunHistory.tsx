"use client";

import React from "react";

import { GlassCard } from "@/components/ui/GlassComponents";
import { formatDateTime, formatRelativeTime } from "@/lib/dateFormat";
import type { WorkflowRun } from "@/services/workflowService";

type Props = {
  runs: WorkflowRun[];
  isLoading?: boolean;
};

const statusTone: Record<string, string> = {
  completed: "border-emerald-400/20 bg-emerald-500/10 text-emerald-200",
  partial_failure: "border-amber-400/20 bg-amber-500/10 text-amber-200",
  failed: "border-rose-400/20 bg-rose-500/10 text-rose-200",
  running: "border-sky-400/20 bg-sky-500/10 text-sky-200",
};

export default function WorkflowRunHistory({ runs, isLoading = false }: Props) {
  return (
    <GlassCard className="border-(--line) bg-(--panel) p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--purple)">
            Run History
          </p>
          <h4 className="mt-2 text-xl font-black text-(--t-1)">Recent workflow executions</h4>
        </div>
      </div>

      {isLoading ? (
        <div className="mt-6 rounded-4xl border border-dashed border-(--line) bg-(--line-2) p-5 text-sm text-(--t-3)">
          Loading workflow runs...
        </div>
      ) : runs.length === 0 ? (
        <div className="mt-6 rounded-4xl border border-dashed border-(--line) bg-(--line-2) p-5 text-sm text-(--t-3)">
          No workflow runs yet. Use the test action or wait for the trigger to fire.
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {runs.map((run) => (
            <div key={run.id} className="rounded-4xl border border-(--line) bg-(--line-2) p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-3 py-1 text-[10px] font-black uppercase tracking-[0.2em] ${
                        statusTone[run.status] || "border-(--line) bg-(--line-2) text-(--t-1)"
                      }`}
                    >
                      {run.status.replace("_", " ")}
                    </span>
                    <span className="text-xs text-(--t-3)">{run.trigger_event}</span>
                  </div>
                  <p className="mt-3 text-sm font-semibold text-(--t-1)">
                    Triggered {run.triggered_at ? formatRelativeTime(run.triggered_at) : "recently"}
                  </p>
                  <p className="mt-1 text-xs text-(--t-3)">
                    {run.completed_at ? formatDateTime(run.completed_at) : "Still running"}
                  </p>
                </div>
                <div className="min-w-[220px] rounded border border-(--line) bg-(--line-2) px-4 py-3 text-xs text-(--t-2)">
                  {run.action_results.length} action{run.action_results.length === 1 ? "" : "s"}
                </div>
              </div>

              <div className="mt-4 grid gap-2 md:grid-cols-2">
                {run.action_results.map((result, index) => (
                  <div
                    key={`${run.id}-${index}`}
                    className="rounded border border-(--line) bg-(--line-2) px-4 py-3 text-xs text-(--t-2)"
                  >
                    <p className="font-black uppercase tracking-[0.18em] text-(--t-3)">
                      {String(result.type || "action")}
                    </p>
                    <p className="mt-2 text-sm text-(--t-1)">
                      {String(result.status || "unknown")}
                    </p>
                    {result.error ? (
                      <p className="mt-2 text-xs text-rose-300">{String(result.error)}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
