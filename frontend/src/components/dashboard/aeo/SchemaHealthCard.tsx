import React from "react";
import Card from "@/components/ui/Card";

type MissingHighImpactType = {
  type: string;
  count: number;
  percentage: number;
};

type HighImpactBlocker = {
  type: string;
  severity: "critical" | "high" | "medium" | "low";
  recommendation: string;
};

type SchemaHealthCardProps = {
  avgScore: number;
  healthyAudits: number;
  issueCount: number;
  coveragePercent: number;
  coverageByType: Record<string, number>;
  missingHighImpactTypes: MissingHighImpactType[];
  highImpactBlockers: HighImpactBlocker[];
};

const clampScore = (score: number) => Math.max(0, Math.min(100, score));

const prettifySchemaType = (value: string): string => {
  const normalized = value.trim();
  if (!normalized) return "Unknown";
  return normalized
    .replace(/^https?:\/\/schema\.org\//i, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
};

const severityClasses: Record<HighImpactBlocker["severity"], string> = {
  critical: "text-rose-300 border-rose-700/50 bg-rose-900/20",
  high: "text-amber-300 border-amber-700/50 bg-amber-900/20",
  medium: "text-yellow-300 border-yellow-700/50 bg-yellow-900/20",
  low: "text-emerald-300 border-emerald-700/50 bg-emerald-900/20",
};

const defaultRecommendation = (type: string): string =>
  `Implement JSON-LD for ${type} with @context, @type, name, description, and canonical URL.`;

export default function SchemaHealthCard({
  avgScore,
  healthyAudits,
  issueCount,
  coveragePercent,
  coverageByType,
  missingHighImpactTypes,
  highImpactBlockers,
}: SchemaHealthCardProps) {
  const score = clampScore(avgScore);
  const coverage = clampScore(coveragePercent);
  const typeBreakdown = Object.entries(coverageByType)
    .sort((a, b) => b[1] - a[1])
    .map(([type, percent]) => ({
      type: prettifySchemaType(type),
      percent: clampScore(percent),
    }));

  const normalizedMissingTypes = missingHighImpactTypes
    .map((item) => ({
      ...item,
      type: prettifySchemaType(item.type),
    }))
    .filter((item) => item.type !== "Unknown");

  const mergedBlockers = normalizedMissingTypes.map((missingType) => {
    const matchedBlocker = highImpactBlockers.find(
      (blocker) => prettifySchemaType(blocker.type).toLowerCase() === missingType.type.toLowerCase()
    );

    return {
      type: missingType.type,
      count: missingType.count,
      percentage: missingType.percentage,
      severity: matchedBlocker?.severity ?? "high",
      recommendation: matchedBlocker?.recommendation || defaultRecommendation(missingType.type),
    };
  });

  const fallbackBlockers = highImpactBlockers
    .filter(
      (blocker) =>
        !mergedBlockers.some(
          (item) => item.type.toLowerCase() === prettifySchemaType(blocker.type).toLowerCase()
        )
    )
    .map((blocker) => ({
      type: prettifySchemaType(blocker.type),
      count: 0,
      percentage: 0,
      severity: blocker.severity,
      recommendation:
        blocker.recommendation || defaultRecommendation(prettifySchemaType(blocker.type)),
    }));

  const actionableBlockers = [...mergedBlockers, ...fallbackBlockers];

  return (
    <Card className="space-y-4 p-6">
      <div>
        <h3 className="text-lg font-semibold text-(--t-1)">Schema Health Score</h3>
        <p className="text-sm text-(--t-2)">Average schema coverage and markup quality.</p>
      </div>

      <div>
        <p className="text-3xl font-black text-primary">{Math.round(score)}</p>
        <div className="mt-2 h-3 rounded-full bg-(--line-2)">
          <div
            className="h-3 w-(--bw) rounded-full bg-cyan-400"
            style={{ "--bw": `${score}%` } as React.CSSProperties}
          />
        </div>
      </div>

      <div className="rounded-xl border border-cyan-500/20 bg-cyan-900/10 p-4 shadow-inner">
        <p className="text-[10px] font-bold tracking-widest uppercase text-(--purple)">
          Schema coverage
        </p>
        <p className="mt-2 text-2xl font-bold text-cyan-100">{Math.round(coverage)}%</p>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-xl border border-(--line) bg-(--line-2) p-4 shadow-inner">
          <p className="text-[10px] font-bold tracking-widest uppercase text-(--t-3)">
            Healthy Audits
          </p>
          <p className="mt-2 text-lg font-bold text-(--t-1)">{healthyAudits}</p>
        </div>
        <div className="rounded-xl border border-(--line) bg-(--line-2) p-4 shadow-inner">
          <p className="text-[10px] font-bold tracking-widest uppercase text-(--t-3)">
            Schema Issues
          </p>
          <p className="mt-2 text-lg font-bold text-(--t-1)">{issueCount}</p>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-bold tracking-widest uppercase text-(--t-3)">
          Coverage by schema type
        </p>
        {typeBreakdown.length === 0 ? (
          <p className="text-sm text-(--t-2)">No schema coverage data yet.</p>
        ) : (
          <ul className="space-y-1 text-sm text-(--t-1)">
            {typeBreakdown.map((item) => (
              <li
                className="flex items-center justify-between rounded-md px-2 py-1 transition-colors hover:bg-(--line-2)"
                key={item.type}
              >
                <span className="text-(--t-2)">{item.type}</span>
                <span className="font-semibold text-(--t-1)">{Math.round(item.percent)}%</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-4 rounded-xl border border-amber-500/20 bg-amber-500/10 p-5 shadow-inner">
        <div>
          <p className="text-[10px] font-bold tracking-widest uppercase text-amber-500">
            High-impact AI answers blockers
          </p>
          <p className="mt-1 text-sm text-(--t-2)">
            Prioritize missing high-impact schema types to improve extractability and direct answer
            eligibility.
          </p>
        </div>

        {actionableBlockers.length === 0 ? (
          <p className="text-sm text-(--t-2)">
            No high-impact blockers detected for the selected audits.
          </p>
        ) : (
          <ul className="space-y-2 text-sm text-(--t-1)">
            {actionableBlockers.map((blocker) => (
              <li
                key={`${blocker.type}-${blocker.recommendation}`}
                className="rounded-xl border border-(--line) bg-(--line-2) p-4 shadow-inner"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold text-(--t-1)">{blocker.type}</p>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs uppercase ${severityClasses[blocker.severity]}`}
                  >
                    {blocker.severity}
                  </span>
                </div>
                <p className="mt-2 text-xs text-(--t-2)">
                  Missing in {blocker.count} audits ({Math.round(blocker.percentage)}%).
                </p>
                <p className="mt-2 text-sm text-(--purple)">{blocker.recommendation}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
