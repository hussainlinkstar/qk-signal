import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "next/navigation";
import { Award, Sparkles, Zap, Search, Loader2, Trash2, BookOpen } from "lucide-react";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { cx } from "@/components/ui/utils";
import { getScoreColor } from "@/lib/scoreColors";
import { useJiraExportTracker } from "@/hooks/useJiraExportTracker";
import { ClientSafeDate } from "@/lib/dateFormat";
import { generateAiStrategicInsights } from "@/services/ai/aiStrategicInsightsService";
import {
  createVisibilityQuery,
  deleteVisibilityQuery,
  fetchVisibilityQueries,
  fetchVisibilitySummary,
  updateVisibilityQuery,
} from "@/services/monitoringService";
import {
  VISIBILITY_PROVIDER_LABELS,
  VISIBILITY_STATUS_COLORS,
  VISIBILITY_STATUS_LABELS,
  isMeasuredVisibilityProvider,
  offeredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";
import type { AuditModuleDiagnostics } from "@/lib/auditNormalization";
import AuditEvidenceStrip from "@/components/results/AuditEvidenceStrip";
import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import { getPlanLockContent } from "@/lib/planLocks";
import type { LockedAuditSection, AeoRewriteSuggestion } from "@/types/auditResult";
import type { GroundedStrategicIdea } from "@/types/aiStrategist";
import type {
  VisibilityProvider,
  VisibilityProviderResult,
  VisibilityQuery,
  VisibilityQuerySummaryRow,
  VisibilitySummaryResponse,
} from "@/types/monitoring";

const AEO_SCORE_LABEL_KEYS = new Set([
  "answerability_score",
  "voice_readiness_score",
  "schema_completeness",
  "content_freshness_score",
]);

type AeoTabProps = {
  aeoScore: number;
  aeoScoreEntries: [string, any][];
  aeoEntityClarity: string | number;
  aeoRecommendations: string[];
  readabilityFindings?: string[];
  rewriteSuggestions?: AeoRewriteSuggestion[];
  moduleDiagnostics?: AuditModuleDiagnostics;
  contextUrl?: string | null;
  entityNames?: string[];
  getAuthHeaders?: () => Promise<Record<string, string>>;
  projectId?: string | number | null;
  auditId?: number | null;
  lockedSection?: LockedAuditSection | null;
};

type TrackedQueryItem = {
  query: string;
  trackedAt: string;
};

type TrackerApiPayload = {
  context_key?: string;
  items?: Array<{
    query?: string;
    tracked_at?: string | null;
  }>;
};

const MANUAL_QUERY_NOTE =
  "Saved as a manual hypothesis. Add project monitoring to validate this query with measured citation telemetry.";

const normalizeTrackingKey = (value: string) => value.trim().toLowerCase();

const buildTrackedQueryIdeas = (trackedQueries: TrackedQueryItem[]): GroundedStrategicIdea[] => {
  return trackedQueries.map((item) => ({
    text: item.query,
    confidence: "low",
    label: "hypothesis",
    source_basis: ["Saved AI answers tracker queries"],
    status_note: MANUAL_QUERY_NOTE,
    last_verified_at: item.trackedAt,
  }));
};

const buildMonitoringStatusNote = (
  results: VisibilityProviderResult[],
  averageScore: number | null
) => {
  const citationsFound = results.reduce(
    (sum, result) => sum + Math.max(0, result.citations_found || 0),
    0
  );

  if (results.some((result) => result.status === "cited")) {
    return `Latest monitoring runs found ${citationsFound} citation(s).`;
  }
  if (results.some((result) => result.status === "not_cited")) {
    if (typeof averageScore === "number" && Number.isFinite(averageScore)) {
      return `Latest monitoring score is ${Math.round(averageScore)} / 100 with no citation wins yet.`;
    }
    return "Latest monitoring runs completed without citation wins.";
  }
  if (results.some((result) => result.status === "failed")) {
    return "Latest monitoring run failed and needs a retry.";
  }
  return "Tracking exists, but a completed monitoring run is not available yet.";
};

const buildMonitoredQueryIdeas = (
  monitoredQueries: VisibilityQuerySummaryRow[]
): GroundedStrategicIdea[] => {
  return monitoredQueries.map((query) => {
    const citationsFound = query.results.reduce(
      (sum, result) => sum + Math.max(0, result.citations_found || 0),
      0
    );

    return {
      text: query.query_text,
      confidence: citationsFound > 0 ? "high" : "medium",
      label: "measured",
      source_basis: [
        "Project visibility monitoring",
        `Providers: ${query.providers.join(", ") || "configured providers"}`,
      ],
      status_note: buildMonitoringStatusNote(query.results, query.average_score),
      last_verified_at: query.last_checked_at,
    } satisfies GroundedStrategicIdea;
  });
};

const ideaLabelTone = (label: GroundedStrategicIdea["label"]) => {
  if (label === "measured") return "success";
  if (label === "inferred") return "info";
  return "warning";
};

const confidenceTone = (confidence: GroundedStrategicIdea["confidence"]) => {
  if (confidence === "high") return "success";
  if (confidence === "medium") return "warning";
  return "danger";
};

const normalizeTrackedQueries = (raw: unknown): TrackedQueryItem[] => {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const payload = item as Record<string, unknown>;
      if (typeof payload.query !== "string" || !payload.query.trim()) return null;
      return {
        query: payload.query.trim(),
        trackedAt:
          typeof payload.trackedAt === "string" && payload.trackedAt.trim()
            ? payload.trackedAt
            : new Date().toISOString(),
      } as TrackedQueryItem;
    })
    .filter((item): item is TrackedQueryItem => item !== null);
};

export default function AeoTab({
  aeoScore,
  aeoScoreEntries,
  aeoEntityClarity,
  aeoRecommendations,
  readabilityFindings = [],
  rewriteSuggestions = [],
  moduleDiagnostics,
  contextUrl,
  getAuthHeaders,
  projectId: propProjectId,
  auditId,
  lockedSection,
}: AeoTabProps) {
  const { t } = useTranslation();
  const params = useParams<{ projectId: string }>();
  const projectId = propProjectId || params?.projectId || "";
  const numericProjectId = useMemo(() => {
    const parsed = Number(projectId);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
  }, [projectId]);
  const hasProjectMonitoring = Boolean(numericProjectId && getAuthHeaders);
  const { getTrackedExport } = useJiraExportTracker(projectId);
  const trackerContextUrl = contextUrl || "workspace";
  const storageKey = useMemo(
    () => `aeo-query-tracker:${trackerContextUrl.toLowerCase()}`,
    [trackerContextUrl]
  );
  const [queryIdeas, setQueryIdeas] = useState<GroundedStrategicIdea[]>([]);
  const [trackedQueries, setTrackedQueries] = useState<TrackedQueryItem[]>([]);
  const [visibilityQueries, setVisibilityQueries] = useState<VisibilityQuery[]>([]);
  const [visibilitySummary, setVisibilitySummary] = useState<VisibilitySummaryResponse | null>(
    null
  );
  const [isGeneratingQueries, setIsGeneratingQueries] = useState(false);
  const [queryError, setQueryError] = useState("");
  const [isTrackerLoading, setIsTrackerLoading] = useState(false);
  const [isVisibilityLoading, setIsVisibilityLoading] = useState(false);
  const [activeTrackingKey, setActiveTrackingKey] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(storageKey);
      setTrackedQueries(normalizeTrackedQueries(raw ? JSON.parse(raw) : []));
    } catch {
      setTrackedQueries([]);
    }
  }, [storageKey]);

  useEffect(() => {
    let cancelled = false;

    const loadFromBackend = async () => {
      if (!getAuthHeaders) {
        return;
      }

      setIsTrackerLoading(true);
      try {
        const headers = await getAuthHeaders();
        const response = await fetch(
          `/api/aeo/query-tracker?context_url=${encodeURIComponent(trackerContextUrl)}`,
          {
            method: "GET",
            headers,
          }
        );
        if (!response.ok) {
          throw new Error("Unable to load tracked queries from cloud");
        }
        const payload = (await response.json()) as TrackerApiPayload;
        if (cancelled) return;
        const normalized = (payload.items || [])
          .map((item) => {
            if (!item || typeof item.query !== "string" || !item.query.trim()) return null;
            return {
              query: item.query.trim(),
              trackedAt:
                typeof item.tracked_at === "string" && item.tracked_at.trim()
                  ? item.tracked_at
                  : new Date().toISOString(),
            } as TrackedQueryItem;
          })
          .filter((item): item is TrackedQueryItem => item !== null);
        setTrackedQueries(normalized);
      } catch {
        if (!cancelled) {
          setQueryError(
            (current) =>
              current || "Cloud sync unavailable right now. Using local manual hypothesis cache."
          );
        }
      } finally {
        if (!cancelled) {
          setIsTrackerLoading(false);
        }
      }
    };

    loadFromBackend();

    return () => {
      cancelled = true;
    };
  }, [getAuthHeaders, trackerContextUrl]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(storageKey, JSON.stringify(trackedQueries));
  }, [storageKey, trackedQueries]);

  useEffect(() => {
    if (!getAuthHeaders) return;

    const timeout = window.setTimeout(async () => {
      try {
        const headers = {
          "Content-Type": "application/json",
          ...(await getAuthHeaders()),
        };
        await fetch("/api/aeo/query-tracker", {
          method: "PUT",
          headers,
          body: JSON.stringify({
            context_url: trackerContextUrl,
            items: trackedQueries.map((item) => ({
              query: item.query,
              tracked_at: item.trackedAt,
            })),
          }),
        });
      } catch {
        return;
      }
    }, 500);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [getAuthHeaders, trackedQueries, trackerContextUrl]);

  const loadVisibilityTelemetry = useCallback(async () => {
    if (!hasProjectMonitoring || !numericProjectId || !getAuthHeaders) {
      setVisibilityQueries([]);
      setVisibilitySummary(null);
      return;
    }

    setIsVisibilityLoading(true);
    try {
      const headers = await getAuthHeaders();
      const [queryListPayload, summaryPayload] = await Promise.all([
        fetchVisibilityQueries(numericProjectId, headers, true),
        fetchVisibilitySummary(numericProjectId, headers),
      ]);
      setVisibilityQueries(queryListPayload.queries);
      setVisibilitySummary(summaryPayload);
    } catch (error) {
      setQueryError(
        error instanceof Error
          ? error.message
          : "Unable to load project monitoring telemetry right now."
      );
    } finally {
      setIsVisibilityLoading(false);
    }
  }, [getAuthHeaders, hasProjectMonitoring, numericProjectId]);

  useEffect(() => {
    if (!hasProjectMonitoring) {
      setVisibilityQueries([]);
      setVisibilitySummary(null);
      return;
    }

    void loadVisibilityTelemetry();
  }, [hasProjectMonitoring, loadVisibilityTelemetry]);

  const monitoredQueries = useMemo(
    () => visibilityQueries.filter((query) => query.query_type === "aeo"),
    [visibilityQueries]
  );
  const monitoredQueryMap = useMemo(
    () => new Map(monitoredQueries.map((query) => [normalizeTrackingKey(query.query_text), query])),
    [monitoredQueries]
  );
  const monitoredSummaryRows = useMemo(
    () => (visibilitySummary?.queries ?? []).filter((query) => query.query_type === "aeo"),
    [visibilitySummary]
  );
  const manualTrackedQueries = useMemo(
    () => trackedQueries.filter((item) => !monitoredQueryMap.has(normalizeTrackingKey(item.query))),
    [monitoredQueryMap, trackedQueries]
  );
  // SIGV2-1215: adding a prompt from here must not select a withdrawn engine,
  // so the plan roster is filtered before its first entry is taken.
  //
  // The empty case returns an empty list, not a guess. It used to fall back to
  // a hardcoded `["google"]`, which fires whenever the summary has not loaded
  // yet, so a prompt could be created against Gemini on a plan that does not
  // measure Gemini. That prompt then looks healthy and is never measured
  // again: it is exactly how five of the six prompts on the preprod project
  // ended up stranded, with four search-type cards reading "No prompt data
  // yet" while the prompts sat there. An empty list lets the backend assign
  // the plan's own first engine, which is the only side that knows the plan.
  const monitoringProviders = useMemo<VisibilityProvider[]>(() => {
    const offered = offeredVisibilityProviders(visibilitySummary?.entitlements.allowed_providers);
    return offered.length ? [offered[0]] : [];
  }, [visibilitySummary?.entitlements.allowed_providers]);

  useEffect(() => {
    if (queryIdeas.length > 0) {
      return;
    }

    const fallbackIdeas = [
      ...buildMonitoredQueryIdeas(monitoredSummaryRows),
      ...buildTrackedQueryIdeas(manualTrackedQueries),
    ];
    if (fallbackIdeas.length === 0) {
      return;
    }

    setQueryIdeas(fallbackIdeas);
  }, [manualTrackedQueries, monitoredSummaryRows, queryIdeas.length]);

  const saveManualQuery = useCallback((query: string) => {
    const normalized = query.trim();
    if (!normalized) return;
    setTrackedQueries((current) => {
      if (
        current.some(
          (item) => normalizeTrackingKey(item.query) === normalizeTrackingKey(normalized)
        )
      ) {
        return current;
      }
      return [
        {
          query: normalized,
          trackedAt: new Date().toISOString(),
        },
        ...current,
      ];
    });
  }, []);

  const removeManualQuery = useCallback((query: string) => {
    setTrackedQueries((current) =>
      current.filter((item) => normalizeTrackingKey(item.query) !== normalizeTrackingKey(query))
    );
  }, []);

  const enableTracking = useCallback(
    async (query: string) => {
      if (!hasProjectMonitoring || !numericProjectId || !getAuthHeaders) {
        saveManualQuery(query);
        return;
      }

      const normalized = query.trim();
      if (!normalized) return;

      const trackingKey = normalizeTrackingKey(normalized);
      const existing = monitoredQueryMap.get(trackingKey);

      setActiveTrackingKey(trackingKey);
      setQueryError("");
      try {
        const headers = await getAuthHeaders();
        if (existing) {
          if (!existing.is_active) {
            await updateVisibilityQuery(
              numericProjectId,
              existing.id,
              { is_active: true },
              headers
            );
          }
        } else {
          await createVisibilityQuery(
            numericProjectId,
            {
              query_text: normalized,
              query_type: "aeo",
              providers: monitoringProviders,
            },
            headers
          );
        }
        await loadVisibilityTelemetry();
      } catch (error) {
        setQueryError(
          error instanceof Error
            ? error.message
            : "Unable to enable project monitoring for this query."
        );
      } finally {
        setActiveTrackingKey(null);
      }
    },
    [
      getAuthHeaders,
      hasProjectMonitoring,
      loadVisibilityTelemetry,
      monitoredQueryMap,
      monitoringProviders,
      numericProjectId,
      saveManualQuery,
    ]
  );

  const disableTracking = useCallback(
    async (query: string) => {
      const trackingKey = normalizeTrackingKey(query);
      const existing = monitoredQueryMap.get(trackingKey);

      if (hasProjectMonitoring && numericProjectId && getAuthHeaders && existing?.is_active) {
        setActiveTrackingKey(trackingKey);
        setQueryError("");
        try {
          const headers = await getAuthHeaders();
          await deleteVisibilityQuery(numericProjectId, existing.id, headers);
          await loadVisibilityTelemetry();
        } catch (error) {
          setQueryError(
            error instanceof Error ? error.message : "Unable to remove monitoring for this query."
          );
        } finally {
          setActiveTrackingKey(null);
        }
        return;
      }

      removeManualQuery(query);
    },
    [
      getAuthHeaders,
      hasProjectMonitoring,
      loadVisibilityTelemetry,
      monitoredQueryMap,
      numericProjectId,
      removeManualQuery,
    ]
  );

  const generateQueryIdeasWithAI = useCallback(async () => {
    setQueryError("");
    setIsGeneratingQueries(true);
    try {
      if (!auditId) {
        throw new Error("Grounded queries require a saved audit.");
      }

      const insights = await generateAiStrategicInsights({
        auditId,
        projectId: numericProjectId,
      });
      if (!insights || insights.aeo_query_ideas.length === 0) {
        throw new Error("No grounded AI answers query ideas were available for this audit yet.");
      }
      setQueryIdeas(insights.aeo_query_ideas);
    } catch (error) {
      setQueryError(
        error instanceof Error
          ? error.message
          : "Unable to load grounded AI answers query ideas right now."
      );
    } finally {
      setIsGeneratingQueries(false);
    }
  }, [auditId, numericProjectId]);

  useEffect(() => {
    if (!auditId) {
      return;
    }

    void generateQueryIdeasWithAI();
  }, [auditId, generateQueryIdeasWithAI]);

  if (lockedSection?.is_locked) {
    return (
      <PlanLockNotice
        {...getPlanLockContent("semanticGraph", {
          requiredPlanLabel: lockedSection.required_plan_label?.trim(),
          title: "AI answers schema insights are locked on the current plan",
          description:
            lockedSection.detail?.trim() ||
            "Upgrade this workspace to unlock semantic graph mapping, schema health analysis, and structured data coverage scoring.",
        })}
        badgeLabel="Locked in API payload"
        align="center"
        className="mx-auto max-w-4xl"
      />
    );
  }

  return (
    <div className="space-y-12 pb-12">
      {moduleDiagnostics ? (
        <AuditEvidenceStrip
          title="AI answers recommendation evidence"
          diagnostics={moduleDiagnostics}
          className="border-[color-mix(in_srgb,var(--purple)_20%,transparent)] "
        />
      ) : null}

      <div className="grid gap-8 lg:grid-cols-2">
        {(() => {
          const scoreColor = getScoreColor(aeoScore);

          return (
            <div className="relative group">
              <div className="relative space-y-6">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <h3 className="flex items-center gap-3 font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
                      <Award className="h-4 w-4 text-primary" />
                      Readiness Score
                    </h3>
                    <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      AI Response Readiness
                    </p>
                  </div>
                  <div className="flex items-baseline gap-1">
                    <div
                      className={cx("text-4xl font-black score-glow", scoreColor.text)}
                      style={{ "--score-glow-color": `${scoreColor.hex}40` } as React.CSSProperties}
                    >
                      {Math.round(aeoScore)}
                    </div>
                    <span className="text-xs font-black text-(--t-3)">/100</span>
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  {aeoScoreEntries
                    .filter(
                      ([key, value]) => typeof value === "number" && AEO_SCORE_LABEL_KEYS.has(key)
                    )
                    .slice(0, 4)
                    .map(([key, value]) => (
                      <div
                        key={key}
                        className="rounded border border-(--line) bg-(--panel) p-4 transition-colors hover:bg-(--line-2)"
                      >
                        <div className="mb-2 font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
                          {t(`signalAuditReport.signalLabels.${key}`)}
                        </div>
                        <div className="font-mono text-sm font-black text-(--t-1) transition-colors group-hover/entry:text-primary">
                          {Math.round(value)}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          );
        })()}

        <div className="relative group">
          <div className="relative flex h-full flex-col space-y-6 overflow-hidden">
            <div className="space-y-4">
              <h3 className="flex items-center gap-3 font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
                <Sparkles className="h-4 w-4 text-(--purple)" />
                Entity Clarity
              </h3>
              <p className="rounded-[10px] bg-(--line-2) px-[14px] py-3 text-[12.5px] text-(--t-2)">
                {typeof aeoEntityClarity === "number"
                  ? t("signalAuditReport.scoreOutOf", {
                      value: Math.round(aeoEntityClarity),
                    })
                  : aeoEntityClarity}
              </p>
            </div>

            <div className="flex-1 space-y-6">
              <div className="flex items-center gap-3">
                <h4 className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
                  Critical Optimizations
                </h4>
                <div className="h-px flex-1 bg-(--line-2)" />
              </div>
              <ul className="grid gap-3">
                {aeoRecommendations.map((rec, i) => (
                  <li
                    key={i}
                    className="group/rec flex items-start gap-4 rounded-xl border border-(--line) p-3 transition-all hover:bg-(--line-2)"
                  >
                    <div className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-lg border border-[color-mix(in_srgb,var(--purple)_20%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] text-(--purple) transition-colors group-hover/rec:bg-[color-mix(in_srgb,var(--purple)_20%,transparent)] group-hover/rec:text-(--purple)">
                      <Zap className="h-2.5 w-2.5" />
                    </div>
                    <span className="text-[11px] font-bold uppercase tracking-wide text-(--t-2) transition-colors group-hover/rec:text-(--t-1)">
                      {rec}
                    </span>
                    <div className="ml-auto flex shrink-0 items-center gap-2">
                      {(() => {
                        const trackedExport = getTrackedExport(`aeo-rec:${rec}`);
                        return trackedExport ? (
                          <a
                            href={trackedExport.issueUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--good)_30%,transparent)] bg-[color-mix(in_srgb,var(--good)_8%,transparent)] px-2 py-1 font-mono text-[10.5px] tracking-[0.06em] text-(--t-1)"
                          >
                            {trackedExport.issueKey}
                          </a>
                        ) : null;
                      })()}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>

      {(readabilityFindings.length > 0 || rewriteSuggestions.length > 0) && (
        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <h3 className="flex items-center gap-3 font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
              <BookOpen className="h-4 w-4 text-primary" />
              Readability &amp; Extractability
            </h3>
            <div className="h-px flex-1 bg-(--line-2)" />
          </div>
          <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
            How easily an AI system can lift a direct answer out of your copy. Paragraphs below
            score low on complexity checks (long sentences, jargon, buried answers).
          </p>

          <div className="grid gap-6 lg:grid-cols-2">
            {readabilityFindings.length > 0 && (
              <div className="rounded-[10px] bg-(--line-2) px-[14px] py-3">
                <h4 className="mb-4 font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
                  Findings
                </h4>
                <ul className="space-y-3">
                  {readabilityFindings.map((finding, index) => (
                    <li
                      key={index}
                      className="flex items-start gap-3 rounded-xl border border-(--line) p-3 text-[11px] font-bold uppercase tracking-wide text-(--t-2)"
                    >
                      <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                      {finding}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {rewriteSuggestions.length > 0 && (
              <div className="rounded-[10px] bg-(--line-2) px-[14px] py-3">
                <h4 className="mb-4 font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
                  Rewrite Suggestions
                </h4>
                <ul className="space-y-4">
                  {rewriteSuggestions.map((item, index) => (
                    <li key={index} className="space-y-2 rounded-xl border border-(--line) p-4">
                      <p className="border-l-2 border-(--purple) pl-3 text-[11px] italic text-(--t-2)">
                        &ldquo;{item.paragraph}&rdquo;
                      </p>
                      <p className="text-[11px] font-bold text-(--t-1)">{item.suggestion}</p>
                      {typeof item.score === "number" && (
                        <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
                          Readability score: {Math.round(item.score * 100)}/100
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="space-y-8">
        <div className="flex items-center gap-4">
          <h3 className="flex items-center gap-3 font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
            <Search className="h-4 w-4 text-primary" />
            Grounded Query Radar
          </h3>
          <div className="h-px flex-1 bg-(--line-2)" />
          <Button
            variant="outline"
            size="sm"
            onClick={generateQueryIdeasWithAI}
            disabled={isGeneratingQueries}
            className="h-9 px-4"
          >
            {isGeneratingQueries ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Refreshing...
              </>
            ) : (
              "Refresh grounded queries"
            )}
          </Button>
        </div>

        {queryError ? (
          <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
            {queryError}
          </p>
        ) : null}

        {isTrackerLoading ? (
          <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
            Loading saved manual hypotheses...
          </p>
        ) : null}

        {isVisibilityLoading && hasProjectMonitoring ? (
          <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
            Loading project monitoring telemetry...
          </p>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-4 rounded border border-(--line) p-5">
            <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
              Suggested Queries
            </p>
            <div className="max-h-[460px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
              {queryIdeas.length === 0 ? (
                <div className="rounded-[10px] bg-(--line-2) px-[14px] py-3 text-[12.5px] text-(--t-2)">
                  No grounded AI answers queries are available yet. Use project monitoring to
                  capture measured telemetry or save a manual hypothesis when monitoring is not
                  available.
                </div>
              ) : (
                queryIdeas.map((idea, index) => {
                  const query = idea.text;
                  const trackingKey = normalizeTrackingKey(query);
                  const monitoredQuery = monitoredQueryMap.get(trackingKey);
                  const isMonitored = monitoredQuery?.is_active === true;
                  const isManuallySaved = trackedQueries.some(
                    (item) => normalizeTrackingKey(item.query) === trackingKey
                  );
                  const isBusy = activeTrackingKey === trackingKey;
                  const buttonLabel = hasProjectMonitoring
                    ? isMonitored
                      ? "Monitored"
                      : "Monitor"
                    : isManuallySaved
                      ? "Saved"
                      : "Save";
                  const isSelected = hasProjectMonitoring ? isMonitored : isManuallySaved;

                  return (
                    <div
                      key={`${query}-${index}`}
                      className="rounded-xl border border-(--line) bg-black/30 p-3"
                    >
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <Badge color={ideaLabelTone(idea.label)}>{idea.label}</Badge>
                        <Badge color={confidenceTone(idea.confidence)}>
                          {idea.confidence} confidence
                        </Badge>
                        {idea.last_verified_at ? (
                          <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                            Verified <ClientSafeDate date={idea.last_verified_at} format="date" />
                          </span>
                        ) : null}
                      </div>
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-[11px] font-medium leading-relaxed text-(--t-1)">
                          {query}
                        </p>
                        <div className="flex shrink-0 flex-col gap-2">
                          <Button
                            variant={isSelected ? "danger" : "ghost"}
                            size="sm"
                            onClick={() =>
                              void (isSelected ? disableTracking(query) : enableTracking(query))
                            }
                            loading={isBusy}
                            loadingText={
                              isSelected ? "Removing" : hasProjectMonitoring ? "Adding" : "Saving"
                            }
                            className="h-7 px-2.5"
                          >
                            {buttonLabel}
                          </Button>
                        </div>
                      </div>
                      {idea.status_note ? (
                        <p className="mt-2 text-[10px] text-(--t-2)">{idea.status_note}</p>
                      ) : null}
                      {idea.source_basis.length > 0 ? (
                        <p className="mt-2 font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                          Sources: {idea.source_basis.join(" • ")}
                        </p>
                      ) : null}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="space-y-4 rounded border border-primary/20 bg-primary/[0.04] p-5">
            <div className="space-y-2">
              <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-primary">
                {hasProjectMonitoring ? "Monitoring Telemetry" : "Manual Hypothesis Queue"}
              </p>
              <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                {hasProjectMonitoring
                  ? "Measured project visibility runs appear here first. Any legacy saved entries stay labeled as manual hypotheses until a monitored run exists."
                  : "Saved notes only. Citation outcomes appear here only after project monitoring is configured."}
              </p>
            </div>

            {hasProjectMonitoring ? (
              <>
                {monitoredSummaryRows.length === 0 ? (
                  <div className="rounded-[10px] bg-(--line-2) px-[14px] py-3 text-[12.5px] text-(--t-2)">
                    Monitor queries from the left panel to start measured citation tracking.
                  </div>
                ) : (
                  <div className="max-h-[320px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                    {monitoredSummaryRows.map((item) => {
                      const trackingKey = normalizeTrackingKey(item.query_text);
                      return (
                        <div
                          key={item.id}
                          className="space-y-3 rounded-xl border border-(--line) bg-black/30 p-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="space-y-2">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge color="success">measured</Badge>
                                {typeof item.average_score === "number" ? (
                                  <Badge color="info">{Math.round(item.average_score)} / 100</Badge>
                                ) : null}
                              </div>
                              <p className="text-[11px] leading-relaxed text-(--t-1)">
                                {item.query_text}
                              </p>
                            </div>
                            <Button
                              variant="danger"
                              size="sm"
                              onClick={() => void disableTracking(item.query_text)}
                              loading={activeTrackingKey === trackingKey}
                              loadingText="Removing"
                              aria-label={`Remove monitoring for ${item.query_text}`}
                              className="h-7 px-2.5"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>

                          <div className="flex flex-wrap gap-2">
                            {/* SIGV2-1215: a withdrawn engine gets no status
                                badge, even on a prompt that still stores a
                                measurement for it.
                                SIGV2-1216: nor does an engine this plan has
                                stopped measuring. A badge carrying a status
                                nobody refreshes is the same claim. */}
                            {item.results
                              .filter((result) =>
                                isMeasuredVisibilityProvider(
                                  result.provider,
                                  visibilitySummary?.entitlements.allowed_providers
                                )
                              )
                              .map((result) => (
                                <Badge
                                  key={`${item.id}-${result.provider}`}
                                  color={VISIBILITY_STATUS_COLORS[result.status]}
                                >
                                  {VISIBILITY_PROVIDER_LABELS[result.provider]}{" "}
                                  {VISIBILITY_STATUS_LABELS[result.status]}
                                </Badge>
                              ))}
                          </div>

                          <p className="text-[10px] text-(--t-2)">
                            {buildMonitoringStatusNote(item.results, item.average_score)}
                          </p>

                          <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                            {item.last_checked_at ? (
                              <>
                                Last checked{" "}
                                <ClientSafeDate date={item.last_checked_at} format="date" />
                              </>
                            ) : (
                              "Awaiting first monitored run"
                            )}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                )}

                {manualTrackedQueries.length > 0 ? (
                  <div className="space-y-3 border-t border-(--line) pt-4">
                    <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      Manual Hypotheses
                    </p>
                    <div className="max-h-[160px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                      {manualTrackedQueries.map((item) => (
                        <div
                          key={item.query}
                          className="space-y-2 rounded-xl border border-(--line) bg-black/30 p-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="space-y-2">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge color="warning">hypothesis</Badge>
                                <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                                  Saved <ClientSafeDate date={item.trackedAt} format="date" />
                                </span>
                              </div>
                              <p className="text-[11px] leading-relaxed text-(--t-1)">
                                {item.query}
                              </p>
                            </div>
                            <Button
                              variant="danger"
                              size="sm"
                              onClick={() => removeManualQuery(item.query)}
                              aria-label={`Remove manual hypothesis ${item.query}`}
                              className="h-7 px-2.5"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                          <p className="text-[10px] text-(--t-2)">{MANUAL_QUERY_NOTE}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : trackedQueries.length === 0 ? (
              <div className="rounded-[10px] bg-(--line-2) px-[14px] py-3 text-[12.5px] text-(--t-2)">
                Save queries from the left panel to keep a manual hypothesis list for later
                validation.
              </div>
            ) : (
              <div className="max-h-[460px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                {trackedQueries.map((item) => (
                  <div
                    key={item.query}
                    className="space-y-2 rounded-xl border border-(--line) bg-black/30 p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge color="warning">hypothesis</Badge>
                          <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                            Saved <ClientSafeDate date={item.trackedAt} format="date" />
                          </span>
                        </div>
                        <p className="text-[11px] leading-relaxed text-(--t-1)">{item.query}</p>
                      </div>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => removeManualQuery(item.query)}
                        aria-label={`Remove manual hypothesis ${item.query}`}
                        className="h-7 px-2.5"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    <p className="text-[10px] text-(--t-2)">{MANUAL_QUERY_NOTE}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
