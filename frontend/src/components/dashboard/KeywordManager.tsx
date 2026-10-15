"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/components/auth/custom-auth";
import { Trash2, Loader2, Target, Search } from "lucide-react";
import {
  ProjectMonitoringWidgetCard,
  ProjectMonitoringWidgetEmptyState,
  ProjectMonitoringWidgetInlineError,
} from "@/components/dashboard/ProjectMonitoringSection";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

type TargetKeyword = {
  id: number;
  keyword: string;
  search_engine: string;
  language_code: string;
  location_code: number | null;
  is_active: boolean;
  created_at: string;
};

/* ------------------------------------------------------------------ */
/* Main Component                                                      */
/* ------------------------------------------------------------------ */

type Props = {
  projectId: number | string;
  className?: string;
};

/**
 * Management of keywords that already exist. Creation lives on the approved
 * SEO detail Keywords tab (SIGV2-1145), so it does not exist twice: this
 * widget used to carry a second add form on a page the approved MVP does not
 * contain, and the tab's "Add keyword" button pointed here.
 *
 * Removal stays here. The approved "Tracked keywords" table is Keyword,
 * Position and Trend with no row actions, so adding one would be inventing a
 * control the design does not have (the same call SIGV2-1142 made for
 * prompts).
 */
export default function KeywordManager({ projectId, className = "" }: Props) {
  const { t } = useTranslation();
  const { getToken } = useAuth();
  const [keywords, setKeywords] = useState<TargetKeyword[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  /* ------------------------------------------------------------------ */
  /* Fetch keywords                                                      */
  /* ------------------------------------------------------------------ */

  const fetchKeywords = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const response = await fetch(`/api/v1/projects/${projectId}/monitoring/keywords`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error(t("keywordManager.loadFailed"));
      const payload: TargetKeyword[] = await response.json();
      setKeywords(payload);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("keywordManager.unexpected"));
    } finally {
      setLoading(false);
    }
  }, [getToken, projectId, t]);

  useEffect(() => {
    fetchKeywords();
  }, [fetchKeywords]);

  /* ------------------------------------------------------------------ */
  /* Delete keyword                                                      */
  /* ------------------------------------------------------------------ */

  const handleDelete = useCallback(
    async (keywordId: number) => {
      setDeletingId(keywordId);
      setError(null);
      try {
        const token = await getToken();
        const response = await fetch(
          `/api/v1/projects/${projectId}/monitoring/keywords/${keywordId}`,
          {
            method: "DELETE",
            headers: { Authorization: `Bearer ${token}` },
          }
        );
        if (!response.ok) throw new Error(t("keywordManager.removeFailed"));
        setKeywords((prev) => prev.filter((kw) => kw.id !== keywordId));
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : t("keywordManager.unexpected"));
      } finally {
        setDeletingId(null);
      }
    },
    [getToken, projectId, t]
  );

  /* ------------------------------------------------------------------ */
  /* Render                                                              */
  /* ------------------------------------------------------------------ */

  return (
    <div id="tracked-keywords">
      <ProjectMonitoringWidgetCard
        icon={Target}
        title={t("keywordManager.title")}
        description={t("keywordManager.description")}
        className={className}
        iconShellClassName="border-violet-500/30 bg-linear-to-br from-violet-500/20 to-purple-500/20"
        iconClassName="text-violet-400"
      >
        {/* Error state */}
        {error && <ProjectMonitoringWidgetInlineError message={error} />}

        {/* Creation happens on the approved Keywords tab, not twice. */}
        <div className="mb-6 flex flex-col gap-3 rounded-xl border-0 bg-(--line-2) p-4 md:flex-row md:items-center md:justify-between">
          <p className="text-xs text-(--t-2)">{t("keywordManager.addMoved")}</p>
          <Link
            href={`/dashboard/projects/${projectId}/google?tab=keywords`}
            className="inline-flex h-9 flex-none items-center rounded-xl border-0 bg-(--line-2) px-4 text-xs font-semibold text-(--t-1) hover:border-violet-500/40"
          >
            {t("keywordManager.addAction")}
          </Link>
        </div>

        {/* Keyword list */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-(--t-3)" />
          </div>
        ) : keywords.length === 0 ? (
          <ProjectMonitoringWidgetEmptyState
            icon={Target}
            title={t("keywordManager.emptyTitle")}
            description={t("keywordManager.emptyDescription")}
          />
        ) : (
          <div className="space-y-2">
            {keywords.map((kw) => (
              <div
                key={kw.id}
                className="flex items-center justify-between p-3 rounded-xl border-0 bg-(--line-2) hover:bg-(--line-2) transition-all group"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-violet-500/10 border border-violet-500/20">
                    <Search size={12} className="text-violet-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm text-(--t-1) font-medium truncate">{kw.keyword}</p>
                    <p className="text-[10px] text-(--t-3)">
                      {kw.search_engine} · {kw.language_code} ·{" "}
                      {new Date(kw.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(kw.id)}
                  disabled={deletingId === kw.id}
                  className="shrink-0 p-2 rounded-lg text-(--t-3) hover:text-rose-400 hover:bg-rose-500/10 opacity-0 group-hover:opacity-100 disabled:opacity-50 transition-all"
                  aria-label={t("keywordManager.removeLabel", { keyword: kw.keyword })}
                >
                  {deletingId === kw.id ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Trash2 size={14} />
                  )}
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Count footer */}
        {keywords.length > 0 && (
          <div className="mt-4 pt-4 border-t border-(--line)">
            <p className="text-[10px] text-(--t-3) font-bold uppercase tracking-widest">
              {t("keywordManager.trackedCount", { count: keywords.length })}
            </p>
          </div>
        )}
      </ProjectMonitoringWidgetCard>
    </div>
  );
}
