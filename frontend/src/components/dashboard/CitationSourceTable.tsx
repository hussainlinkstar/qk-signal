"use client";

import React from "react";
import Card from "@/components/ui/Card";
import type { GeoCitationSource } from "@/types/auditResult";

type CitationSourceTableProps = {
  sources: GeoCitationSource[];
};

type TrustLevel = "High" | "Medium" | "Low";

const trustLevelFromScore = (trustScore: number): TrustLevel => {
  if (trustScore >= 75) return "High";
  if (trustScore >= 50) return "Medium";
  return "Low";
};

const trustBadgeClassByLevel: Record<TrustLevel, string> = {
  High: "border-emerald-400/40 bg-emerald-500/15 text-emerald-100",
  Medium: "border-amber-400/40 bg-amber-500/15 text-amber-100",
  Low: "border-rose-400/40 bg-rose-500/15 text-rose-100",
};

export default function CitationSourceTable({ sources }: CitationSourceTableProps) {
  return (
    <Card className="p-6">
      <h3 className="text-lg font-semibold text-(--t-1)">Citation sources</h3>
      <p className="mt-1 text-sm text-(--t-2)">Domains with citation frequency and trust score.</p>

      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-(--line) text-left text-xs uppercase tracking-wider text-(--t-2)">
              <th className="py-2 pr-3">Domain</th>
              <th className="py-2 pr-3">Citation count</th>
              <th className="py-2">Trust score</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => {
              const trustLevel = trustLevelFromScore(source.trust_score);
              const roundedTrustScore = Math.round(source.trust_score);

              return (
                <tr
                  key={`${source.owner}-${source.domain}`}
                  className="border-b border-(--line) text-(--t-1)"
                >
                  <td className="py-2 pr-3">{source.domain}</td>
                  <td className="py-2 pr-3">{source.citation_count}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <span
                        title={`${roundedTrustScore} / 100`}
                        className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${trustBadgeClassByLevel[trustLevel]}`}
                      >
                        {trustLevel}
                      </span>
                      <span className="text-xs text-(--t-2)">{roundedTrustScore} / 100</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
