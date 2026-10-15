"use client";

import React from "react";
import { Info, Eye, Brain, Target, Cpu } from "lucide-react";
import Tooltip from "@/components/ui/Tooltip";
import { getScoreColor } from "@/lib/scoreColors";

type SignalItem = {
  label: string;
  score: number;
  description?: string;
  source_tool?: string;
  priority_level?: string;
};

type DetailedSignalListProps = {
  title: string;
  signals: SignalItem[];
};

const DetailedSignalList = ({ title, signals }: DetailedSignalListProps) => {
  if (!signals || signals.length === 0) return null;

  return (
    <div className="rounded-xl border-0 bg-(--line-2) p-6 shadow-sm">
      <h3 className="mb-4 text-lg font-semibold text-(--t-1)">{title}</h3>
      <div className="space-y-4">
        {signals.map((signal) => {
          const colorClasses = getScoreColor(signal.score);

          let badgeClasses = "";
          let BadgeIcon = null;
          if (signal.source_tool) {
            const toolName = signal.source_tool.toLowerCase();
            if (toolName.includes("vision")) {
              badgeClasses =
                "bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] text-indigo-300 border border-[color-mix(in_srgb,var(--purple)_20%,transparent)]";
              BadgeIcon = Eye;
            } else if (toolName.includes("semantic")) {
              badgeClasses =
                "bg-cyan-500/10 text-(--purple) border border-cyan-500/20 shadow-[0_0_10px_rgba(34,211,238,0.1)]";
              BadgeIcon = Brain;
            } else if (toolName.includes("intent")) {
              badgeClasses = "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20";
              BadgeIcon = Target;
            } else if (toolName.includes("technical") || toolName.includes("protocol")) {
              badgeClasses = "bg-amber-500/10 text-amber-300 border border-amber-500/20";
              BadgeIcon = Cpu;
            } else {
              badgeClasses = "bg-slate-700/20 text-(--t-2) border-0";
            }
          }

          return (
            <div key={signal.label} className="space-y-1.5">
              <div className="flex items-start sm:items-center justify-between gap-4 text-sm flex-col sm:flex-row">
                <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                  <span className="font-medium text-(--t-2)">{signal.label}</span>
                  {signal.description && (
                    <Tooltip content={signal.description}>
                      <Info className="h-3.5 w-3.5 text-(--t-3) hover:text-(--t-2) cursor-help" />
                    </Tooltip>
                  )}
                </div>
                <div className="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end">
                  {signal.source_tool && (
                    <span
                      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${badgeClasses}`}
                    >
                      {BadgeIcon && <BadgeIcon className="h-3 w-3" />}
                      {signal.source_tool}
                    </span>
                  )}
                  {signal.priority_level && (
                    <span
                      className={`text-[10px] uppercase font-bold tracking-widest ${
                        signal.priority_level === "Critical"
                          ? "text-red-400"
                          : signal.priority_level === "Strategic"
                            ? "text-purple-400"
                            : "text-(--t-2)"
                      }`}
                    >
                      {signal.priority_level}
                    </span>
                  )}
                  <span className={`font-mono font-medium ${colorClasses.text}`}>
                    {Math.round(signal.score)}/100
                  </span>
                </div>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-(--line-2)">
                <div
                  className="h-full w-(--bw) rounded-full bg-(--c) opacity-(--bo) transition-all duration-500"
                  style={
                    {
                      "--bw": `${Math.max(0, signal.score)}%`,
                      "--bo": signal.score === 0 ? 0 : 1,
                      "--c": colorClasses.hex,
                    } as React.CSSProperties
                  }
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DetailedSignalList;
