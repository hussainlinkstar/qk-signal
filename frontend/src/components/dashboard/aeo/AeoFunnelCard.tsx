import React from "react";
import Card from "@/components/ui/Card";
import type { AnswerabilityFunnelData } from "@/components/dashboard/aeo/aeoDashboardAdapters";

const asStageWidth = (stageValue: number, total: number) => {
  if (total <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(100, (stageValue / total) * 100));
};

export default function AeoFunnelCard({ data }: { data: AnswerabilityFunnelData }) {
  const stages = [
    { label: "Total Assessments", value: data.totalAudits, accent: "bg-cyan-400" },
    { label: "AI-Readable Pages", value: data.aiReadablePages, accent: "bg-violet-400" },
    { label: "Direct Answer Hits", value: data.directAnswerHits, accent: "bg-emerald-400" },
  ];

  return (
    <Card className="space-y-5 p-6">
      <div>
        <h3 className="text-xl font-bold tracking-tight text-(--t-1)">Answerability Funnel</h3>
        <p className="mt-1 text-sm font-medium text-(--t-2)">
          Track the flow from audited coverage to direct answer wins, explicit din total audituri.
        </p>
      </div>

      <div className="space-y-4">
        {stages.map((stage) => (
          <div key={stage.label}>
            <div className="mb-1 flex items-center justify-between text-sm">
              <span className="text-(--t-2)">{stage.label}</span>
              <span className="font-semibold text-(--t-1)">
                {stage.value}
                {stage.label === "Total Assessments"
                  ? ""
                  : ` (${Math.round(
                      stage.label === "Direct Answer Hits"
                        ? data.directAnswerHitsShareTotal
                        : (stage.value / Math.max(1, data.totalAudits)) * 100
                    )}% din total audituri)`}
              </span>
            </div>
            <div className="h-2 rounded-full bg-(--line-2) shadow-inner">
              <div
                className={`h-2 rounded-full ${stage.accent} shadow-glow w-(--bw)`}
                style={
                  {
                    "--bw": `${asStageWidth(stage.value, data.totalAudits)}%`,
                  } as React.CSSProperties
                }
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
