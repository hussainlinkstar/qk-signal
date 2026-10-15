"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import {
  CARD_CONTAINER_PRESETS,
  CARD_LABEL_CLASS,
  CARD_SUBSECTION_CLASS,
  DASHBOARD_CARD_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import type {
  UpdateVisibilityQueryPayload,
  VisibilityEntitlements,
  VisibilityProvider,
  VisibilityQuery,
} from "@/types/monitoring";
import {
  SEARCH_TYPE_DESCRIPTIONS,
  SEARCH_TYPE_LABELS,
  VISIBILITY_PROVIDER_LABELS,
  VISIBILITY_QUERY_TYPE_LABELS,
  measuredVisibilityProviders,
  offeredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";

type VisibilityQueryManagerProps = {
  projectId: number | string;
  queries: VisibilityQuery[];
  entitlements: VisibilityEntitlements | null;
  loading?: boolean;
  error?: string | null;
  onUpdate: (queryId: number, payload: UpdateVisibilityQueryPayload) => Promise<void>;
  onDelete: (queryId: number) => Promise<void>;
};

export default function VisibilityQueryManager({
  projectId,
  queries,
  entitlements,
  loading = false,
  error = null,
  onUpdate,
  onDelete,
}: VisibilityQueryManagerProps) {
  const { t } = useTranslation();
  const [busyQueryId, setBusyQueryId] = useState<number | null>(null);
  const [providerDrafts, setProviderDrafts] = useState<Record<number, VisibilityProvider[]>>({});

  // SIGV2-1215: a withdrawn engine is not selectable, and a prompt that still
  // stores one does not offer it back.
  const allowedProviders = offeredVisibilityProviders(entitlements?.allowed_providers);
  const limitReached = Boolean(
    entitlements &&
    entitlements.max_queries > 0 &&
    entitlements.used_queries >= entitlements.max_queries
  );

  const visibleQueries = useMemo(
    () => [...queries].sort((left, right) => Number(right.is_active) - Number(left.is_active)),
    [queries]
  );

  // SIGV2-1216: a prompt stored while the plan still measured an engine keeps
  // naming it, so the toggles are narrowed to what the plan measures now.
  // Nothing is written back: the stored selection survives, and an upgrade
  // restores the engine without the customer re-entering it.
  const providerDraftFor = (query: VisibilityQuery) =>
    providerDrafts[query.id] ??
    measuredVisibilityProviders(query.providers, entitlements?.allowed_providers);

  const handleToggleActive = async (query: VisibilityQuery, nextActive: boolean) => {
    setBusyQueryId(query.id);
    try {
      await onUpdate(query.id, { is_active: nextActive });
    } finally {
      setBusyQueryId(null);
    }
  };

  const handleSaveProviders = async (query: VisibilityQuery) => {
    const draft = providerDraftFor(query);
    setBusyQueryId(query.id);
    try {
      await onUpdate(query.id, { providers: draft });
    } finally {
      setBusyQueryId(null);
    }
  };

  const handleDelete = async (queryId: number) => {
    setBusyQueryId(queryId);
    try {
      await onDelete(queryId);
    } finally {
      setBusyQueryId(null);
    }
  };

  return (
    <Card
      className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS} border-(--border) bg-(--card)`}
    >
      <div className="space-y-2">
        <p className={CARD_LABEL_CLASS}>AI Visibility</p>
        <h2 className={TYPO.sectionTitle}>Visibility Query Manager</h2>
        <p className="text-sm text-(--muted-foreground)">
          Configure the prompts and providers used to monitor AI citation coverage for this project.
        </p>
      </div>

      {error ? (
        <div className="rounded border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {error}
        </div>
      ) : null}

      <div className={`${CARD_SUBSECTION_CLASS} border-0 bg-(--card)`}>
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <p className={CARD_LABEL_CLASS}>{t("visibilityQueryManager.planUsageLabel")}</p>
            <p className="text-sm font-semibold text-(--foreground)">
              {entitlements
                ? t("visibilityQueryManager.planUsage", {
                    used: entitlements.used_queries,
                    max: entitlements.max_queries,
                    remaining: Math.max(
                      0,
                      entitlements.remaining_queries ??
                        entitlements.max_queries - entitlements.used_queries
                    ),
                  })
                : t("visibilityQueryManager.planUsageLoading")}
            </p>
          </div>
          {entitlements ? (
            <Badge color={entitlements.is_locked || limitReached ? "warning" : "success"}>
              {entitlements.plan_label || entitlements.plan.replace(/_/g, " ")}
            </Badge>
          ) : null}
        </div>

        <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className="text-xs text-(--muted-foreground)">
            {t("visibilityQueryManager.addMoved")}
          </p>
          <Link
            href={`/dashboard/projects/${projectId}/ai-answers?tab=prompts`}
            className="inline-flex h-9 flex-none items-center rounded-md border-0 bg-(--background) px-4 text-xs font-semibold text-(--foreground) hover:border-(--foreground)/30"
          >
            {t("visibilityQueryManager.addAction")}
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-10 text-sm text-(--muted-foreground)">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading visibility queries...
        </div>
      ) : visibleQueries.length === 0 ? (
        <div
          className={`${CARD_SUBSECTION_CLASS} border border-dashed border-(--border) bg-(--card) text-sm text-(--muted-foreground)`}
        >
          No visibility queries configured yet.
        </div>
      ) : (
        <div className="space-y-4">
          {visibleQueries.map((query) => {
            const draftProviders = providerDraftFor(query);
            const providersChanged = draftProviders.join("|") !== query.providers.join("|");

            return (
              <div
                key={query.id}
                className={`${CARD_SUBSECTION_CLASS} border-0 bg-(--card)`}
              >
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-(--foreground)">
                        {query.query_text}
                      </h3>
                      <Badge color={query.is_active ? "success" : "default"}>
                        {query.is_active ? "Active" : "Paused"}
                      </Badge>
                      <Badge color="teal">{VISIBILITY_QUERY_TYPE_LABELS[query.query_type]}</Badge>
                      {/* SIGV2-1186: a generated prompt has to be tellable
                          from the customer's own, so they can keep it, retype
                          it or delete it with their eyes open. */}
                      {query.is_generated ? <Badge color="violet">Added by Signal</Badge> : null}
                    </div>
                    <p className="text-xs text-(--muted-foreground)">
                      Last updated{" "}
                      {query.updated_at
                        ? new Date(query.updated_at).toLocaleDateString()
                        : "recently"}
                    </p>
                    {/* SIGV2-1197: the scored search type is shown, attributed
                        to Signal, and never chosen. Jake ruled a customer cannot
                        be expected to pick from a dropdown of internal types, so
                        the select SIGV2-1186 added is gone. A wrong assignment
                        is fixed by rewording the question, which Edit on the
                        Prompts tab now supports; the backend reassigns the type
                        from the new wording. */}
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span className="text-xs text-(--muted-foreground)">
                        {t("visibilityQueryManager.searchTypeLabel")}
                      </span>
                      {query.search_type ? (
                        <Badge color="default">{SEARCH_TYPE_LABELS[query.search_type]}</Badge>
                      ) : (
                        <span className="text-xs text-(--muted-foreground)">
                          {t("visibilityQueryManager.searchTypePending")}
                        </span>
                      )}
                      <span className="text-xs text-(--muted-foreground)">
                        {t("visibilityQueryManager.searchTypeAssigned")}
                      </span>
                    </div>
                    {query.search_type ? (
                      <p className="text-xs text-(--muted-foreground)">
                        {SEARCH_TYPE_DESCRIPTIONS[query.search_type]}
                      </p>
                    ) : null}
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <ToggleSwitch
                      checked={query.is_active}
                      onChange={(checked) => void handleToggleActive(query, checked)}
                      disabled={busyQueryId === query.id || (!query.is_active && limitReached)}
                      label="Tracking active"
                    />
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => void handleDelete(query.id)}
                      disabled={busyQueryId === query.id}
                      loading={busyQueryId === query.id}
                      loadingText="Removing"
                    >
                      <Trash2 className="h-4 w-4" />
                      Remove
                    </Button>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  {allowedProviders.map((provider) => {
                    const checked = draftProviders.includes(provider);
                    return (
                      <label
                        key={`${query.id}-${provider}`}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold transition-colors ${
                          checked
                            ? "border-brand-aeo/50 bg-brand-aeo/10 text-brand-aeo"
                            : "border-(--border) bg-(--background) text-(--foreground)"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="sr-only"
                          checked={checked}
                          onChange={() =>
                            setProviderDrafts((current) => ({
                              ...current,
                              [query.id]: draftProviders.includes(provider)
                                ? draftProviders.filter((item) => item !== provider)
                                : [...draftProviders, provider],
                            }))
                          }
                          disabled={busyQueryId === query.id}
                        />
                        {VISIBILITY_PROVIDER_LABELS[provider]}
                      </label>
                    );
                  })}
                </div>

                <div className="mt-4 flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleSaveProviders(query)}
                    disabled={
                      busyQueryId === query.id || !providersChanged || draftProviders.length === 0
                    }
                  >
                    Save providers
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
