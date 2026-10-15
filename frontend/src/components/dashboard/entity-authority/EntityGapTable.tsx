"use client";

import React from "react";

import { GlassCard } from "@/components/ui/GlassComponents";
import { TABLE } from "@/components/ui/tableTokens";
import type { EntityAuthorityGap } from "@/types/entityAuthority";

/**
 * SIGV2-1196: this table reports gaps, it no longer files work. The "Action"
 * column used to carry an "Add to Content Plan" button that created a project
 * task and announced it had landed in the task board, a board the approved
 * sidebar presents as unbuilt and that /tasks renders as SOON. Reporting the
 * gap stays; the invitation to file it somewhere the customer cannot open is
 * what went.
 */
type EntityGapTableProps = {
  gaps: EntityAuthorityGap[];
};

export default function EntityGapTable({ gaps }: EntityGapTableProps) {
  return (
    <GlassCard className="p-6 border-(--line) bg-(--line-2)">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-black uppercase tracking-[0.16em] text-(--t-2)">Entity Gaps</h3>
        <p className="text-xs text-(--t-2)">{gaps.length} missing target entities</p>
      </div>

      {gaps.length === 0 ? (
        <div className="rounded-xl border-0 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          Great coverage. No missing target entities were detected.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border-0">
          <table className="min-w-full text-sm">
            <thead className={TABLE.head}>
              <tr className={TABLE.headerRow}>
                <th className={TABLE.headerCell}>Entity</th>
                <th className={TABLE.headerCell}>Gap Reason</th>
              </tr>
            </thead>
            <tbody>
              {gaps.map((gap) => (
                <tr key={gap.entity_key} className={TABLE.bodyRow}>
                  <td className={TABLE.bodyCell}>
                    <p className="font-semibold text-(--t-1)">{gap.entity_name}</p>
                    <p className="text-xs text-(--t-3)">{gap.entity_key}</p>
                  </td>
                  <td className={TABLE.bodyCell}>{gap.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassCard>
  );
}
