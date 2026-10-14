import type {
  AiStrategicInsights,
  GroundedStrategicIdea,
  GroundingSource,
  PriorityRoadmapItem,
} from "@/types/aiStrategist";
import { HttpLlmProvider } from "@/services/ai/providers/httpLlmProvider";
import type { LlmProvider } from "@/services/ai/providers/llmProvider";

const REQUIRED_KEYS: Array<keyof AiStrategicInsights> = [
  "executive_summary",
  "critical_alerts",
  "priority_roadmap",
  "content_gap_theory",
  "technical_debt_explanation",
  "grounding_sources",
  "aeo_query_ideas",
  "geo_prompt_ideas",
];

export type AiStrategicInsightsRequest = {
  auditId: number;
  projectId?: number | null;
};

const asString = (value: unknown): string | null =>
  typeof value === "string" && value.trim().length > 0 ? value.trim() : null;

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.map((item) => asString(item)).filter((item): item is string => Boolean(item))
    : [];

const asRoadmap = (value: unknown): PriorityRoadmapItem[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map<PriorityRoadmapItem | null>((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return null;
      const row = item as Record<string, unknown>;

      return {
        task: asString(row.task) ?? "",
        category: asString(row.category) ?? "",
        impact: asString(row.impact) ?? "",
        effort_score:
          typeof row.effort_score === "number" ? row.effort_score : Number(row.effort_score ?? 0),
        reasoning: asString(row.reasoning) ?? "",
        confidence:
          row.confidence === "high" || row.confidence === "medium" || row.confidence === "low"
            ? row.confidence
            : undefined,
        label:
          row.label === "measured" || row.label === "inferred" || row.label === "hypothesis"
            ? row.label
            : undefined,
        source_basis: asStringArray(row.source_basis),
      } satisfies PriorityRoadmapItem;
    })
    .filter((item): item is PriorityRoadmapItem => {
      if (!item) return false;
      return Boolean(
        item.task &&
        item.category &&
        item.impact &&
        item.reasoning &&
        Number.isFinite(item.effort_score)
      );
    });
};

const asGroundingSources = (value: unknown): GroundingSource[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map<GroundingSource | null>((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return null;
      const row = item as Record<string, unknown>;
      const label = asString(row.label);
      const sourceType = asString(row.source_type);
      const measured = typeof row.measured === "boolean" ? row.measured : null;

      if (!label || !sourceType || measured === null) {
        return null;
      }

      return {
        label,
        source_type: sourceType,
        measured,
        updated_at: asString(row.updated_at),
      } satisfies GroundingSource;
    })
    .filter((item): item is GroundingSource => item !== null);
};

const asGroundedIdeas = (value: unknown): GroundedStrategicIdea[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map<GroundedStrategicIdea | null>((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return null;
      const row = item as Record<string, unknown>;
      const text = asString(row.text);
      const confidence =
        row.confidence === "high" || row.confidence === "medium" || row.confidence === "low"
          ? row.confidence
          : null;
      const label =
        row.label === "measured" || row.label === "inferred" || row.label === "hypothesis"
          ? row.label
          : null;

      if (!text || !confidence || !label) {
        return null;
      }

      return {
        text,
        confidence,
        label,
        source_basis: asStringArray(row.source_basis),
        status_note: asString(row.status_note),
        last_verified_at: asString(row.last_verified_at),
      } satisfies GroundedStrategicIdea;
    })
    .filter((item): item is GroundedStrategicIdea => item !== null);
};

export const parseAiStrategicInsights = (raw: string): AiStrategicInsights | null => {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;

    const missingKey = REQUIRED_KEYS.find((key) => !(key in parsed));
    if (missingKey) {
      return null;
    }

    const normalized: AiStrategicInsights = {
      executive_summary: asString(parsed.executive_summary) ?? "",
      critical_alerts: asStringArray(parsed.critical_alerts).slice(0, 2),
      priority_roadmap: asRoadmap(parsed.priority_roadmap).slice(0, 3),
      content_gap_theory: asStringArray(parsed.content_gap_theory).slice(0, 3),
      technical_debt_explanation: asString(parsed.technical_debt_explanation) ?? "",
      generated_at: asString(parsed.generated_at) ?? new Date().toISOString(),
      audit_id:
        typeof parsed.audit_id === "number" && Number.isFinite(parsed.audit_id)
          ? parsed.audit_id
          : undefined,
      project_id:
        typeof parsed.project_id === "number" && Number.isFinite(parsed.project_id)
          ? parsed.project_id
          : null,
      grounding_sources: asGroundingSources(parsed.grounding_sources),
      aeo_query_ideas: asGroundedIdeas(parsed.aeo_query_ideas),
      geo_prompt_ideas: asGroundedIdeas(parsed.geo_prompt_ideas),
    };

    const isValid =
      Boolean(normalized.executive_summary.trim()) &&
      normalized.critical_alerts.length > 0 &&
      normalized.priority_roadmap.length > 0 &&
      normalized.content_gap_theory.length > 0 &&
      Boolean(normalized.technical_debt_explanation.trim());

    return isValid ? normalized : null;
  } catch {
    return null;
  }
};

export const generateAiStrategicInsights = async (
  request: AiStrategicInsightsRequest,
  provider: LlmProvider = new HttpLlmProvider()
): Promise<AiStrategicInsights | null> => {
  const completion = await provider.complete({
    audit_id: request.auditId,
    project_id: request.projectId ?? undefined,
  });
  return parseAiStrategicInsights(completion.content);
};
