"use client";

import React from "react";

import { GlassCard } from "@/components/ui/GlassComponents";
import type { EntityAuthorityBreakdown as EntityAuthorityBreakdownType } from "@/types/entityAuthority";

type EntityAuthorityBreakdownProps = {
  breakdown: EntityAuthorityBreakdownType;
};

const BREAKDOWN_META: Array<{
  key: keyof EntityAuthorityBreakdownType;
  label: string;
  weight: string;
  colorClass: string;
}> = [
  { key: "coverage", label: "Entity Coverage", weight: "40%", colorClass: "bg-cyan-400" },
  { key: "depth", label: "Entity Depth", weight: "35%", colorClass: "bg-teal-400" },
  { key: "consistency", label: "Entity Consistency", weight: "15%", colorClass: "bg-blue-400" },
  { key: "uniqueness", label: "Entity Uniqueness", weight: "10%", colorClass: "bg-amber-400" },
];

export default function EntityAuthorityBreakdown({ breakdown }: EntityAuthorityBreakdownProps) {
  return (
    <GlassCard className="p-6 border-(--line) bg-(--line-2)">
      <div className="space-y-4">
        <h3 className="text-sm font-black uppercase tracking-[0.16em] text-(--t-2)">
          Component Breakdown
        </h3>
        {BREAKDOWN_META.map((item) => {
          const value = Math.max(0, Math.min(100, breakdown[item.key]));
          return (
            <div key={item.key} className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-(--t-2)">
                <span className="font-semibold text-(--t-1)">{item.label}</span>
                <span className="font-black uppercase tracking-wider">
                  {item.weight} weight · {value.toFixed(1)}
                </span>
              </div>
              <div className="h-3 overflow-hidden rounded-full border border-(--line) bg-[color-mix(in_srgb,var(--panel)_80%,transparent)]">
                <div
                  className={`h-full w-(--bw) ${item.colorClass}`}
                  style={{ "--bw": `${value}%` } as React.CSSProperties}
                />
              </div>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}
