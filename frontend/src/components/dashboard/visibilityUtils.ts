import {
  WITHDRAWN_VISIBILITY_PROVIDERS,
  type SearchTypeId,
  type VisibilityProvider,
  type VisibilityQueryStatus,
} from "@/types/monitoring";

// The KEYS are the backend's provider contract (`VisibilityProvider`, which
// mirrors SUPPORTED_VISIBILITY_PROVIDERS) and are gated against the committed
// backend vocabulary by `src/types/monitoring.providerContract.test.ts`. Meta
// was keyed `meta_ai` here until SIGV2-1163; the backend has never sent that,
// so a real `meta` row fell through to no label at all.
//
// The LABELS are the backend's own VISIBILITY_PROVIDER_LABELS verbatim: the
// consumer engine each slot measures ("Gemini", "ChatGPT", "Copilot",
// "Llama"). Jake asked for this directly in #qiko-signal (SIGV2-1161):
// "this should be actual LLMs using OpenRouter shouldn't it? Not the Bedrock
// models? Please fix this". His complaint reads like it is about the
// measurement path, but it is not: live measurement already runs through
// OpenRouter since SIGV2-1023 with Bedrock only as the fallback (the
// measurement question itself is tracked under SIGV2-1183 and this change
// does not touch it). What he was seeing was this map *displaying* Bedrock
// model names, which made the product look like it measures with Bedrock.
// The labels were the defect; the measurement was already correct.
//
// The approved design names consumer engines only (mockup: Signal AIO
// Detail.html), and the label strings are gated against
// contracts/visibility_providers.json by
// src/types/monitoring.providerContract.test.ts, so this map cannot drift
// from the backend again. The old strings were also just wrong on three
// rows: "Qwen3 235B" for Gemini, "GLM-5" for Perplexity, "GLM-4.7" for Grok.
//
// SIGV2-1215: `bing` ("Copilot") keeps its entry even though Copilot is
// withdrawn from the product. The map is the vocabulary, not the offer: a
// recorded measurement has to resolve to a name. Nothing renders it, because
// every list of providers a surface is about to display goes through
// `offeredVisibilityProviders` below.
export const VISIBILITY_PROVIDER_LABELS: Record<VisibilityProvider, string> = {
  openai: "ChatGPT",
  google: "Gemini",
  anthropic: "Claude",
  deepseek: "DeepSeek",
  perplexity: "Perplexity",
  xai: "Grok",
  bing: "Copilot",
  meta: "Llama",
};

/**
 * Drop withdrawn engines from a provider list before it is rendered
 * (SIGV2-1215).
 *
 * The backend already filters withdrawn engines out of every payload. This is
 * the display-side half of the same rule, so a cached response, an older
 * backend or a list the client assembles itself cannot put a Copilot row back
 * on screen. Order is preserved; nothing is substituted when the result is
 * empty, because an empty engine list is the honest answer.
 */
export const offeredVisibilityProviders = <T extends string>(
  providers: readonly T[] | null | undefined
): T[] =>
  (providers ?? []).filter(
    (provider) => !(WITHDRAWN_VISIBILITY_PROVIDERS as readonly string[]).includes(provider)
  );

/** Whether a single provider key may be shown to a customer. */
export const isOfferedVisibilityProvider = (provider: string): boolean =>
  !(WITHDRAWN_VISIBILITY_PROVIDERS as readonly string[]).includes(provider);

/**
 * Narrow a provider list to the engines this project's plan measures
 * (SIGV2-1216).
 *
 * `offeredVisibilityProviders` answers "does the product offer this engine".
 * This answers "does this project's plan measure it", which is the question
 * every surface that reports a measurement actually needs. The two were the
 * same fact until a plan roster shrank: Specialist stopped measuring Gemini,
 * so a prompt stored while it did keeps naming an engine nobody re-measures,
 * and the cell it last recorded would otherwise sit on screen forever.
 *
 * The backend filters all of this already. This is the display-side half, for
 * the same reason as SIGV2-1215: a cached response or an older backend must
 * not be able to put the row back.
 *
 * `allowedProviders` null or undefined means "no roster in scope" and leaves
 * the offered list alone, so a payload that has not loaded yet cannot empty a
 * list that should be full.
 */
export const measuredVisibilityProviders = <T extends string>(
  providers: readonly T[] | null | undefined,
  allowedProviders: readonly string[] | null | undefined
): T[] => {
  const offered = offeredVisibilityProviders(providers);
  if (!allowedProviders) {
    return offered;
  }
  const measured = new Set<string>(allowedProviders);
  return offered.filter((provider) => measured.has(provider));
};

/** Whether a single provider key may be shown for a project on this plan. */
export const isMeasuredVisibilityProvider = (
  provider: string,
  allowedProviders: readonly string[] | null | undefined
): boolean =>
  isOfferedVisibilityProvider(provider) &&
  (!allowedProviders || allowedProviders.includes(provider));

export const VISIBILITY_QUERY_TYPE_LABELS: Record<"aeo" | "geo", string> = {
  aeo: "AI answers",
  geo: "AI visibility",
};

// SIGV2-1186. The backend sends a `label` with every coverage entry
// (`SEARCH_TYPE_LABELS`), so this map is only the fallback for a prompt row,
// where the API sends the id alone. It is the backend's own wording verbatim,
// and the one-line explanation is what each type means to the customer: the
// question "how does this prompt map to the type you scored it under" needs an
// answer in the UI, not just in the taxonomy.
export const SEARCH_TYPE_LABELS: Record<SearchTypeId, string> = {
  brand: "Brand",
  category: "Category",
  problem: "Problem",
  feature: "Feature",
  comparison: "Comparison",
};

export const SEARCH_TYPE_DESCRIPTIONS: Record<SearchTypeId, string> = {
  brand: "Someone asking about you by name.",
  category: "Someone asking who the options are, without naming you.",
  problem: "Someone describing a problem you solve, not a product.",
  feature: "Someone asking what you do, what it includes or what it costs.",
  comparison: "Someone weighing you against an alternative.",
};

export const VISIBILITY_STATUS_LABELS: Record<VisibilityQueryStatus, string> = {
  pending: "Pending",
  cited: "Cited",
  not_cited: "Not cited",
  failed: "Failed",
};

export const VISIBILITY_STATUS_COLORS: Record<
  VisibilityQueryStatus,
  "default" | "success" | "danger" | "warning"
> = {
  pending: "default",
  cited: "success",
  not_cited: "danger",
  failed: "warning",
};

export const formatVisibilityPercent = (value: number | null | undefined): string =>
  typeof value === "number" ? `${Math.round(value)}%` : "Pending";

export const formatVisibilityDate = (value: string | null | undefined): string =>
  value ? new Date(value).toLocaleDateString() : "Not run yet";
