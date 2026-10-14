import type {
  VisibilityProviderResult,
  VisibilityProvider,
  VisibilitySummaryResponse,
} from "@/types/monitoring";

/**
 * Whether an engine's answers actually came from that engine.
 *
 * `live` is the only value that supports the claim the row's label makes. The
 * measurement falls back to a controlled Bedrock panel whenever the live call
 * does not happen, and the model behind a slot there is a different vendor
 * (the `google` slot is served by Qwen, `perplexity` by GLM, `anthropic` and
 * `bing` by Nova). The backend has always recorded which of the two produced a
 * run, as `engine_source` on the cell and `presence.live_measured` per run;
 * until SIGV2-1299 no surface read either, so a stand-in answer was presented
 * under a consumer engine name with nothing to distinguish it.
 *
 * `unmeasured` is deliberately distinct from `fallback`. A pending, failed or
 * explicitly unmeasured cell has no provenance to report, and claiming one
 * would repeat the defect SIGV2-1104 and SIGV2-1263 fixed elsewhere: an
 * absence of measurement presented as a measurement.
 */
export type EngineProvenance = "live" | "fallback" | "mixed" | "unmeasured";

const LIVE_ENGINE_SOURCE = "openrouter_live";
/** `project_visibility_service` collapses several sources to this marker. */
const MIXED_ENGINE_SOURCE = "mixed";

type CellProvenance = "live" | "fallback" | "mixed" | null;

function cellProvenance(cell: VisibilityProviderResult): CellProvenance {
  if (cell.status === "pending" || cell.status === "failed") return null;
  if (cell.presence?.state === "unmeasured") return null;

  if (cell.engine_source) {
    if (cell.engine_source === MIXED_ENGINE_SOURCE) return "mixed";
    return cell.engine_source === LIVE_ENGINE_SOURCE ? "live" : "fallback";
  }
  // No `engine_source` on the cell: the per-run `live_measured` flag carries
  // the same fact and is the older of the two fields.
  if (cell.presence) return cell.presence.live_measured ? "live" : "fallback";
  return null;
}

/** The provenance of one engine's cells, taken together. */
export function engineProvenance(cells: VisibilityProviderResult[]): EngineProvenance {
  const resolved = cells
    .map(cellProvenance)
    .filter((value): value is "live" | "fallback" | "mixed" => value !== null);
  if (resolved.length === 0) return "unmeasured";
  if (resolved.includes("mixed")) return "mixed";

  const live = resolved.filter((value) => value === "live").length;
  if (live === resolved.length) return "live";
  if (live === 0) return "fallback";
  return "mixed";
}

/**
 * Provenance per engine across the whole summary, for the surfaces that render
 * one row per engine. Engines with no cells are absent from the map rather
 * than defaulted, so a caller cannot read a missing engine as a live one.
 */
export function provenanceByProvider(
  summary: VisibilitySummaryResponse
): Partial<Record<VisibilityProvider, EngineProvenance>> {
  const cells = (summary.queries ?? []).flatMap((query) => query.results ?? []);
  const byProvider: Partial<Record<VisibilityProvider, EngineProvenance>> = {};
  for (const provider of new Set(cells.map((cell) => cell.provider))) {
    byProvider[provider] = engineProvenance(cells.filter((cell) => cell.provider === provider));
  }
  return byProvider;
}
