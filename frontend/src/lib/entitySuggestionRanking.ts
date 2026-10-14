import type { EntityChipItem } from "@/components/results/EntityChips";
import { getAuditEntities, normalizeAuditReport } from "@/lib/reportAdapters";

type AuditHistoryEntitySource = {
  created_at?: string | null;
  full_report?: Record<string, unknown> | null;
};

type AggregatedEntity = {
  name: string;
  type: string;
  confidence: number | null;
  frequency: number;
  latestSeenAt: number | null;
};

const DAY_IN_MS = 24 * 60 * 60 * 1000;

const recencyScore = (latestSeenAt: number | null, nowTs: number) => {
  if (!latestSeenAt) return 0;
  const daysSinceSeen = Math.max(0, (nowTs - latestSeenAt) / DAY_IN_MS);
  return Math.max(0, 10 - daysSinceSeen);
};

export const rankEntitySuggestionsFromHistory = (
  history: AuditHistoryEntitySource[],
  selectedEntities: EntityChipItem[],
  options?: { limit?: number; nowTs?: number }
): EntityChipItem[] => {
  const limit = options?.limit ?? 10;
  const nowTs = options?.nowTs ?? Date.now();
  const selected = new Set(selectedEntities.map((entity) => entity.name.trim().toLowerCase()));
  const aggregated = new Map<string, AggregatedEntity>();

  history.forEach((record) => {
    const createdTs = Date.parse(record.created_at ?? "");
    const normalizedReport = normalizeAuditReport(record.full_report ?? {});
    const entities = getAuditEntities(normalizedReport);
    const seenInRecord = new Set<string>();

    entities.forEach((entity) => {
      const name = entity.name.trim();
      if (!name) return;

      const key = name.toLowerCase();
      if (selected.has(key) || seenInRecord.has(key)) return;
      seenInRecord.add(key);

      const confidence = typeof entity.relevance === "number" ? entity.relevance : null;
      const current = aggregated.get(key);

      if (!current) {
        aggregated.set(key, {
          name,
          type: entity.type?.trim() || "Entity",
          confidence,
          frequency: 1,
          latestSeenAt: Number.isFinite(createdTs) ? createdTs : null,
        });
        return;
      }

      current.frequency += 1;
      if (confidence !== null) {
        current.confidence =
          current.confidence === null ? confidence : Math.max(current.confidence, confidence);
      }
      if (Number.isFinite(createdTs)) {
        current.latestSeenAt =
          current.latestSeenAt === null ? createdTs : Math.max(current.latestSeenAt, createdTs);
      }
    });
  });

  return Array.from(aggregated.values())
    .map((entry) => ({
      ...entry,
      score: entry.frequency * 10 + recencyScore(entry.latestSeenAt, nowTs),
    }))
    .sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      if ((right.confidence ?? -1) !== (left.confidence ?? -1)) {
        return (right.confidence ?? -1) - (left.confidence ?? -1);
      }
      return left.name.localeCompare(right.name);
    })
    .slice(0, limit)
    .map(({ name, type, confidence }) => ({ name, type, confidence }));
};
