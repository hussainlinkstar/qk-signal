"use client";

import React from "react";
import { AlertCircle, Search } from "lucide-react";

import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import {
  CARD_CONTAINER_PRESETS,
  CARD_LABEL_CLASS,
  CARD_SUBSECTION_CLASS,
  DASHBOARD_CARD_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TABLE } from "@/components/ui/tableTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import type { VisibilityProviderResult, VisibilitySummaryResponse } from "@/types/monitoring";
import {
  VISIBILITY_PROVIDER_LABELS,
  VISIBILITY_QUERY_TYPE_LABELS,
  VISIBILITY_STATUS_COLORS,
  VISIBILITY_STATUS_LABELS,
  formatVisibilityDate,
  formatVisibilityPercent,
  measuredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";

type VisibilityQueryGridProps = {
  summary: VisibilitySummaryResponse | null;
  loading?: boolean;
  error?: string | null;
};

function StatusBadge({ result }: { result: VisibilityProviderResult | undefined }) {
  const status = result?.status ?? "pending";

  return (
    <Badge color={VISIBILITY_STATUS_COLORS[status]} className="justify-center">
      <span
        aria-label={`${result?.provider ?? "provider"} status ${VISIBILITY_STATUS_LABELS[status]}`}
      >
        {VISIBILITY_STATUS_LABELS[status]}
      </span>
    </Badge>
  );
}

export default function VisibilityQueryGrid({
  summary,
  loading = false,
  error = null,
}: VisibilityQueryGridProps) {
  if (loading) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="animate-pulse space-y-4">
          <div className="h-3 w-36 rounded bg-(--line-2)" />
          <div className="h-7 w-64 rounded bg-(--line-2)" />
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="h-14 rounded border-0 bg-(--line-2)" />
            ))}
          </div>
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="flex items-center gap-3 text-amber-300">
          <AlertCircle className="h-5 w-5" />
          <div>
            <p className={CARD_LABEL_CLASS}>AI Visibility</p>
            <h2 className={TYPO.sectionTitle}>Query Visibility Grid</h2>
            <p className="mt-2 text-sm text-(--t-2)">{error}</p>
          </div>
        </div>
      </Card>
    );
  }

  const queries = summary?.queries ?? [];
  // SIGV2-1215: withdrawn engines get no column, in the table or in the
  // mobile cards, even when the summary still lists them.
  // SIGV2-1216: nor does an engine this plan has stopped measuring. A column
  // holding one frozen cell per prompt is the clearest form of the defect.
  const providers = measuredVisibilityProviders(
    summary?.providers,
    summary?.entitlements?.allowed_providers
  );

  if (!summary || queries.length === 0) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <p className={CARD_LABEL_CLASS}>AI Visibility</p>
        <h2 className={TYPO.sectionTitle}>Query Visibility Grid</h2>
        <p className="text-sm text-(--t-2)">
          No tracked queries yet. Add your first AI answers or AI visibility prompt to start
          monitoring provider coverage.
        </p>
      </Card>
    );
  }

  if (summary.completed_checks === 0) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <p className={CARD_LABEL_CLASS}>AI Visibility</p>
        <h2 className={TYPO.sectionTitle}>Query Visibility Grid</h2>
        <p className="text-sm text-(--t-2)">
          Queries are configured, but the first provider runs have not completed yet.
        </p>
      </Card>
    );
  }

  return (
    <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
      <div className="space-y-2">
        <p className={CARD_LABEL_CLASS}>AI Visibility</p>
        <h2 className={TYPO.sectionTitle}>Query Visibility Grid</h2>
        <p className="text-sm text-(--t-2)">
          Track where your brand is cited across each monitored prompt and provider.
        </p>
      </div>

      <div className="hidden overflow-x-auto lg:block">
        <table className="min-w-full border-separate border-spacing-y-2">
          <thead className={TABLE.head}>
            <tr className={TABLE.headerRow}>
              <th className={TABLE.headerCell}>Query</th>
              {providers.map((provider) => (
                <th key={provider} className={TABLE.headerCell}>
                  {VISIBILITY_PROVIDER_LABELS[provider]}
                </th>
              ))}
              <th className={TABLE.headerCell}>Avg. Score</th>
              <th className={TABLE.headerCell}>Last Checked</th>
            </tr>
          </thead>
          <tbody>
            {queries.map((query) => (
              <tr key={query.id} className={TABLE.bodyRow}>
                <td className={`${TABLE.bodyCell} min-w-[280px]`}>
                  <div className="flex items-start gap-3">
                    <div className="mt-1 flex h-8 w-8 items-center justify-center rounded-xl border-0 bg-(--line-2) text-(--t-2)">
                      <Search className="h-4 w-4" />
                    </div>
                    <div className="space-y-2">
                      <p className="text-sm font-semibold text-(--t-1)">{query.query_text}</p>
                      <Badge color="teal">{VISIBILITY_QUERY_TYPE_LABELS[query.query_type]}</Badge>
                    </div>
                  </div>
                </td>
                {providers.map((provider) => (
                  <td key={`${query.id}-${provider}`} className={TABLE.bodyCell}>
                    <StatusBadge
                      result={query.results.find((result) => result.provider === provider)}
                    />
                  </td>
                ))}
                <td className={TABLE.bodyCell}>
                  <span className="text-sm font-semibold text-(--t-1)">
                    {formatVisibilityPercent(query.average_score)}
                  </span>
                </td>
                <td className={TABLE.bodyCell}>
                  <span className="text-sm text-(--t-2)">
                    {formatVisibilityDate(query.last_checked_at)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 lg:hidden">
        {queries.map((query) => (
          <div
            key={query.id}
            className={`${CARD_SUBSECTION_CLASS} border-0 bg-[color-mix(in_srgb,var(--panel)_50%,transparent)]`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-2">
                <p className="text-sm font-semibold text-(--t-1)">{query.query_text}</p>
                <Badge color="teal">{VISIBILITY_QUERY_TYPE_LABELS[query.query_type]}</Badge>
              </div>
              <span className="text-sm font-semibold text-(--t-1)">
                {formatVisibilityPercent(query.average_score)}
              </span>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {providers.map((provider) => (
                <div
                  key={`${query.id}-${provider}-mobile`}
                  className="rounded border-0 bg-(--line-2) p-3"
                >
                  <p className={CARD_LABEL_CLASS}>{VISIBILITY_PROVIDER_LABELS[provider]}</p>
                  <div className="mt-2">
                    <StatusBadge
                      result={query.results.find((result) => result.provider === provider)}
                    />
                  </div>
                </div>
              ))}
            </div>

            <p className="mt-4 text-xs text-(--t-3)">
              Last checked: {formatVisibilityDate(query.last_checked_at)}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
}
