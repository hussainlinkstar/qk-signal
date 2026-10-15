"use client";

import React from "react";
import type { WorkspaceLead } from "@/services/workspaceService";
import LeadScoreBadge from "@/components/dashboard/LeadScoreBadge";
import { ClientSafeDate } from "@/lib/dateFormat";
import { cx } from "@/components/ui/utils";

type LeadsTableProps = {
  leads: WorkspaceLead[];
};

const statusDotClass = "h-1.5 w-1.5 shrink-0 rounded-full";

function statusStyle(status: string) {
  switch (status) {
    case "audit_complete":
      return {
        dot: "bg-emerald-400",
        badge: "bg-emerald-500/10 text-emerald-400",
        label: "Completed",
      };
    case "pending":
      return { dot: "bg-amber-400", badge: "bg-amber-500/10 text-amber-400", label: "Pending" };
    case "failed":
      return { dot: "bg-rose-400", badge: "bg-rose-500/10 text-rose-400", label: "Failed" };
    default:
      return {
        dot: "bg-slate-400",
        badge: "bg-(--line-2) text-(--t-2)",
        label: status.replace("_", " "),
      };
  }
}

export default function LeadsTable({ leads }: LeadsTableProps) {
  if (leads.length === 0) {
    return null;
  }

  const isExternalHttpUrl = (value: string) => /^https?:\/\//i.test(value || "");

  return (
    <div className="rounded-lg border-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-(--border) bg-(--surface-subtle) text-left text-xs uppercase tracking-wider text-(--muted-foreground)">
              <th className="px-4 py-3">Lead</th>
              <th className="px-4 py-3">URL</th>
              <th className="px-4 py-3">Scores</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Created</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((lead) => {
              const s = statusStyle(lead.status);
              return (
                <tr
                  key={lead.id}
                  className="border-b border-(--border) text-(--foreground) transition-colors hover:bg-(--line-2)"
                >
                  <td className="px-4 py-3">
                    <p className="font-medium text-(--foreground)">{lead.email}</p>
                    {lead.entity ? (
                      <p className="text-xs text-(--muted-foreground)">{lead.entity}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    {isExternalHttpUrl(lead.url) ? (
                      <a
                        href={lead.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-primary hover:underline truncate max-w-[200px] inline-block"
                      >
                        {lead.url}
                      </a>
                    ) : (
                      <span className="text-(--muted-foreground)">Not provided</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <LeadScoreBadge label="AI visibility" score={lead.scores?.geo} />
                      <LeadScoreBadge label="SEO" score={lead.scores?.seo} />
                      <LeadScoreBadge label="AI answers" score={lead.scores?.aeo} />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cx(
                        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
                        s.badge
                      )}
                    >
                      <span className={cx(statusDotClass, s.dot)} />
                      {s.label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-(--muted-foreground)">
                    {lead.created_at ? (
                      <ClientSafeDate date={lead.created_at} format="datetime" />
                    ) : (
                      "--"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
