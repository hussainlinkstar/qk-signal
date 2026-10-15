import React from "react";
import { BrainCircuit, AlertTriangle, ShieldCheck, Zap, Activity } from "lucide-react";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";

type DeepAnalysisProps = {
  grid: NonNullable<CanonicalAuditReport["debate_findings"]>;
  executiveSummary?: string;
  competitivePositioning?: string;
  generativeMetrics?: CanonicalAuditReport["generative_authority_metrics"];
};

export default function DeepAnalysis({
  grid,
  executiveSummary,
  competitivePositioning,
  generativeMetrics,
}: DeepAnalysisProps) {
  if (!grid || grid.length === 0) return null;

  const normalizeSeverity = (severity: unknown): string => {
    if (typeof severity !== "string") return "";
    return severity.trim().toLowerCase();
  };

  const getSeverityColor = (severity: unknown) => {
    switch (normalizeSeverity(severity)) {
      case "critical":
        return "text-red-400 bg-red-500/10 border-red-500/20";
      case "strategic":
        return "text-amber-400 bg-amber-500/10 border-amber-500/20";
      case "evolutionary":
        return "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
      default:
        return "text-(--t-2) bg-(--line-2) border-(--line)";
    }
  };

  const getSeverityLabel = (severity: unknown): string => {
    if (typeof severity !== "string") return "Unknown";
    const trimmedSeverity = severity.trim();
    return trimmedSeverity.length > 0 ? trimmedSeverity : "Unknown";
  };

  const getLayerIcon = (layer: string) => {
    switch (layer) {
      case "Neural Vision":
        return <BrainCircuit className="h-5 w-5 text-brand-geo" />;
      case "Knowledge Graph":
        return <Activity className="h-5 w-5 text-brand-aeo" />;
      case "Generative Reasoning":
        return <Zap className="h-5 w-5 text-brand-geo" />;
      case "Protocol Lab":
        return <ShieldCheck className="h-5 w-5 text-brand-aeo" />;
      default:
        return <BrainCircuit className="h-5 w-5 text-(--t-2)" />;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 border-b border-(--line) pb-4">
        <div className="rounded-xl bg-brand-geo/15 p-2.5">
          <BrainCircuit className="h-6 w-6 text-brand-geo" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-(--t-1)">Deep Analysis</h2>
          <p className="text-sm text-(--t-2)">
            Cross-signal analysis and strategic recommendations.
          </p>
        </div>
      </div>

      {executiveSummary && (
        <div className="rounded-xl border-0 bg-brand-geo/5 p-5">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-brand-geo">
            Executive Summary
          </h3>
          <p className="text-sm leading-relaxed text-(--t-2)">{executiveSummary}</p>
        </div>
      )}

      {generativeMetrics && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border-0 bg-(--line-2) p-4">
            <div className="text-xs font-semibold uppercase text-(--t-3)">Entity Clarity</div>
            <div className="mt-1 text-2xl font-bold text-(--t-1)">
              {generativeMetrics.entity_clarity_score}
              <span className="text-sm text-(--t-3)">/100</span>
            </div>
          </div>
          <div className="rounded-xl border-0 bg-(--line-2) p-4">
            <div className="text-xs font-semibold uppercase text-(--t-3)">Contextual Trust</div>
            <div className="mt-1 text-2xl font-bold text-(--t-1)">
              {generativeMetrics.contextual_trust_score}
              <span className="text-sm text-(--t-3)">/100</span>
            </div>
          </div>
          <div className="rounded-xl border-0 bg-(--line-2) p-4">
            <div className="text-xs font-semibold uppercase text-(--t-3)">Citation Density</div>
            <div className="mt-1 text-lg font-bold text-(--t-1) tracking-wide">
              {generativeMetrics.citable_nugget_density}
            </div>
          </div>
        </div>
      )}

      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-(--t-1)">Debate Findings</h3>
        <div className="grid gap-4">
          {grid.map((item, index) => (
            <div
              key={index}
              className="overflow-hidden rounded-xl border-0 bg-(--line-2) shadow-lg"
            >
              <div className="flex items-center justify-between border-b border-(--line) bg-(--line-2) px-5 py-3">
                <div className="flex items-center gap-2 font-medium text-(--t-1)">
                  {getLayerIcon(item.layer)}
                  <span>{item.layer}</span>
                </div>
                <div
                  className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${getSeverityColor(item?.severity)}`}
                >
                  {getSeverityLabel(item?.severity)}
                </div>
              </div>

              <div className="p-5 space-y-4">
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-(--t-3)">
                    Observation
                  </h4>
                  <p className="mt-1 text-sm text-(--t-2)">{item.finding}</p>
                </div>

                <div className="relative overflow-hidden rounded-lg border-0 bg-brand-geo/5 p-4">
                  <div className="absolute left-0 top-0 h-full w-1 bg-brand-geo/50"></div>
                  <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-brand-geo">
                    <Zap className="h-3.5 w-3.5" /> Cross-Signal Insight
                  </h4>
                  <p className="mt-2 text-sm leading-relaxed text-(--t-1)">
                    {item.neural_correlation}
                  </p>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-lg bg-(--line-2) p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-(--t-3)">
                      LLM Behavior Impact
                    </h4>
                    <p className="mt-1 text-sm text-(--t-2) ">"{item.llm_behavior_projection}"</p>
                  </div>
                  <div className="rounded-lg border-0 bg-brand-aeo/10 p-4">
                    <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-brand-aeo">
                      <AlertTriangle className="h-3.5 w-3.5" /> Recommended Fix
                    </h4>
                    <p className="mt-1 text-sm text-(--t-1)">{item.architect_fix}</p>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {competitivePositioning && (
        <div className="mt-8 rounded-xl border-0 bg-brand-geo/5 p-5">
          <h3 className="mb-3 text-sm font-bold uppercase tracking-wider text-brand-geo">
            Competitive Positioning
          </h3>
          <div className="prose prose-sm prose-invert max-w-none text-(--t-2)">
            {competitivePositioning.split("\n").map((paragraph, idx) => (
              <p key={idx} className="mb-2 last:mb-0">
                {paragraph}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
