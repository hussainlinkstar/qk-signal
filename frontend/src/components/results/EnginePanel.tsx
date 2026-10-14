import React from "react";
import { ChevronRight, Radio } from "lucide-react";

import { cx } from "@/components/ui/utils";

type EnginePanelProps = {
  className?: string;
};

type Engine = {
  id: string;
  /** Display name shown in the panel. */
  name: string;
  /** Underlying model family used to measure this engine on the live panel. */
  via: string;
};

const ENGINES: Engine[] = [
  { id: "chatgpt", name: "ChatGPT", via: "OpenAI GPT" },
  { id: "gemini", name: "Gemini", via: "Google Gemini" },
  { id: "claude", name: "Claude", via: "Anthropic" },
  { id: "perplexity", name: "Perplexity", via: "Perplexity Sonar" },
  { id: "grok", name: "Grok", via: "xAI Grok" },
  { id: "deepseek", name: "DeepSeek", via: "DeepSeek" },
];

const LIVE_PANEL_COPY = "Measured directly on the live consumer AI engines.";

/**
 * Presentational "Live engine tracking" panel for the report Overview surface.
 *
 * Live engine tracking is included on every plan, so this panel carries no
 * plan gate (SIGV2-1108). The backend grants it unconditionally:
 * `CAPABILITY_MATRIX` in `backend/app/config/plans.py` sets
 * `has_live_engine_tracking: True` for all five plans and
 * `MINIMUM_PLAN_BY_FEATURE` maps the feature to `plan_starter`. Showing an
 * "upgrade to Executive" prompt here sold a capability the customer already
 * had, and upgrading changed nothing. Which engines each plan measures is a
 * separate ladder, settled per plan in `VISIBILITY_PLAN_LIMITS`
 * (SIGV2-1188).
 *
 * The honest-labelling invariant still holds: each row names the engine and
 * the model family behind it, and we never claim a user's exact ranking on a
 * named consumer engine. Bing/Copilot was already absent here because it had
 * no live measurement path, and since SIGV2-1215 it is withdrawn from the
 * product altogether.
 */
export default function EnginePanel({ className }: EnginePanelProps) {
  return (
    <div className={cx("space-y-6", className)} data-testid="engine-panel">
      <div className="space-y-1">
        <h3 className="flex items-center gap-3 text-sm font-black uppercase tracking-[0.2em] text-(--t-1)">
          <ChevronRight className="h-4 w-4 text-primary" />
          Live engine tracking
        </h3>
        <p className="pl-7 text-xs font-medium text-(--t-3)">{LIVE_PANEL_COPY}</p>
      </div>
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {ENGINES.map((engine) => (
          <li
            key={engine.id}
            className="relative flex items-center gap-4 rounded border border-(--line) bg-(--line-2) p-4 shadow-inner transition-colors hover:bg-(--line-2)"
            data-testid={`engine-${engine.id}`}
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-emerald-400/30  text-emerald-300">
              <Radio className="h-3.5 w-3.5" />
            </div>
            <div className="flex-1 space-y-0.5">
              <p className="text-sm font-semibold leading-snug text-(--t-1)">{engine.name}</p>
              <p className="text-[11px] leading-relaxed text-(--t-2)">{engine.via}</p>
            </div>
            <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest text-emerald-300">
              Live
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
