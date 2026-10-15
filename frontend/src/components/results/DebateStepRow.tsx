"use client";

import React from "react";

export type DebateStep = {
  role: string;
  semantic_role?: "generator" | "critic" | "judge" | "consolidator" | null;
  provider: string;
  model: string;
  output_summary: string;
  token_usage: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
  latency_ms: number;
  routing_mode?: string | null;
  route_reason?: string | null;
  requested_tier?: string | null;
  execution_tier?: string | null;
  layer?: number | null;
};

const ROLE_LABELS: Record<string, { label: string; step: number; color: string }> = {
  proposer: { label: "Proposer", step: 1, color: "text-thoth-brass" },
  challenger: { label: "Challenger", step: 2, color: "text-amber-400" },
  synthesizer: { label: "Synthesizer", step: 3, color: "text-thoth-logic" },
  fast_proposer: { label: "FAST Proposer", step: 1, color: "text-thoth-brass" },
  fast_critic: { label: "FAST Critic", step: 2, color: "text-amber-400" },
  fast_synthesizer: { label: "FAST Synthesizer", step: 3, color: "text-thoth-logic" },
  seo_generator: { label: "SEO Generator", step: 1, color: "text-thoth-brass" },
  aeo_geo_generator: { label: "AIO Generator", step: 1, color: "text-thoth-brass" },
  geo_generator: { label: "AI Visibility Generator", step: 1, color: "text-thoth-brass" },
  aeo_generator: { label: "AI Answers Generator", step: 1, color: "text-thoth-brass" },
  centralized_critic: { label: "Central Critic", step: 2, color: "text-amber-400" },
  seo_critic: { label: "SEO Critic", step: 2, color: "text-amber-400" },
  geo_critic: { label: "AI Visibility Critic", step: 2, color: "text-amber-400" },
  aeo_critic: { label: "AI Answers Critic", step: 2, color: "text-amber-400" },
  smart_synthesizer: { label: "SMART Synthesizer", step: 3, color: "text-thoth-logic" },
  magistrate: { label: "Magistrate", step: 4, color: "text-thoth-logic" },
  consolidator: { label: "Consolidator", step: 3, color: "text-(--purple)" },
  global_magistrate: { label: "Global Magistrate", step: 4, color: "text-thoth-logic" },
  generator: { label: "Generator", step: 1, color: "text-thoth-brass" },
  critic: { label: "Critic", step: 2, color: "text-amber-400" },
  judge: { label: "Judge", step: 3, color: "text-thoth-logic" },
  consolidator_role: { label: "Consolidator", step: 3, color: "text-(--purple)" },
};

const DebateStepRow = ({ step }: { step: DebateStep }) => {
  const shouldPreferSpecificRole =
    !!step.role &&
    !["proposer", "challenger", "synthesizer", "generator", "critic", "judge"].includes(step.role);
  const labelKey = shouldPreferSpecificRole
    ? step.role
    : (step.semantic_role ?? step.role ?? "unknown");
  const meta = ROLE_LABELS[labelKey] ?? { label: labelKey, step: 0, color: "text-(--t-2)" };
  const totalTokens = step.token_usage?.total_tokens ?? 0;
  const latencySeconds = (step.latency_ms / 1000).toFixed(1);
  const stepLabel =
    step.layer != null && step.layer > 0 ? `Layer ${step.layer}` : `Step ${meta.step}`;

  return (
    <div className="flex flex-col gap-1 rounded-[12px] border-0 bg-[#EEF1F6] bg-(--line-2) p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-(--line-2) px-2 py-0.5 text-xs font-semibold text-(--t-2)">
            {stepLabel}
          </span>
          <span className={`text-sm font-semibold ${meta.color}`}>{meta.label}</span>
        </div>
        <span className="text-xs text-(--t-3)">
          {step.provider} / {step.model}
        </span>
      </div>
      <p className="text-xs text-(--t-2) line-clamp-2">{step.output_summary}</p>
      <div className="flex items-center gap-3 text-[10px] text-(--t-3)">
        <span>{latencySeconds}s</span>
        <span>{totalTokens > 0 ? `${(totalTokens / 1000).toFixed(1)}k tok` : ",  tok"}</span>
        {step.execution_tier ? <span>{step.execution_tier}</span> : null}
      </div>
    </div>
  );
};

export default DebateStepRow;
