import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "next/navigation";
import { cx } from "@/components/ui/utils";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { ChevronRight, Target, Sparkles, Loader2, Trash2 } from "lucide-react";
import GeoIcon from "@/components/ui/GeoIcon";
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
import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import { getPlanLockContent } from "@/lib/planLocks";
import type { LockedAuditSection } from "@/types/auditResult";
import type { GroundedStrategicIdea } from "@/types/aiStrategist";
import type {
  VisibilityProvider,
  VisibilityProviderResult,
  VisibilityQuery,
  VisibilityQuerySummaryRow,
  VisibilitySummaryResponse,
} from "@/types/monitoring";

type TrackedPromptItem = {
  prompt: string;
  trackedAt: string;
};

type TrackerApiPayload = {
  context_key?: string;
  items?: Array<{
    prompt?: string;
    tracked_at?: string | null;
  }>;
};

type GeoTabProps = {
  geoScore: number;
  geoSummary: string;
  geoTabData: Record<string, any> | null;
  geoRecommendations: string[];
  moduleDiagnostics?: AuditModuleDiagnostics;
  contextUrl?: string | null;
  entityNames?: string[];
  getAuthHeaders?: () => Promise<Record<string, string>>;
  projectId?: string | number | null;
  auditId?: number | null;
  isBrandWithoutUrl?: boolean;
  lockedSection?: LockedAuditSection | null;
};

const MANUAL_PROMPT_NOTE =
  "Saved as a manual hypothesis. Add project monitoring to validate this prompt with measured citation telemetry.";

const normalizeTrackingKey = (value: string) => value.trim().toLowerCase();

const buildTrackedPromptIdeas = (trackedPrompts: TrackedPromptItem[]): GroundedStrategicIdea[] => {
  return trackedPrompts.map((item) => ({
    text: item.prompt,
    confidence: "low",
    label: "hypothesis",
    source_basis: ["Saved AI visibility tracker prompts"],
    status_note: MANUAL_PROMPT_NOTE,
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

const buildMonitoredPromptIdeas = (
  monitoredPrompts: VisibilityQuerySummaryRow[]
): GroundedStrategicIdea[] => {
  return monitoredPrompts.map((query) => {
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

const normalizeTrackedPrompts = (raw: unknown): TrackedPromptItem[] => {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const payload = item as Record<string, unknown>;
      if (typeof payload.prompt !== "string" || !payload.prompt.trim()) return null;
      return {
        prompt: payload.prompt.trim(),
        trackedAt:
          typeof payload.trackedAt === "string" && payload.trackedAt.trim()
            ? payload.trackedAt
            : new Date().toISOString(),
      } as TrackedPromptItem;
    })
    .filter((item): item is TrackedPromptItem => item !== null);
};

export default function GeoTab({
  geoScore,
  geoSummary,
  geoTabData,
  geoRecommendations,
  contextUrl,
  getAuthHeaders,
  projectId: propProjectId,
  auditId,
  isBrandWithoutUrl = false,
  lockedSection,
}: GeoTabProps) {
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
    () => `geo-prompt-tracker:${trackerContextUrl.toLowerCase()}`,
    [trackerContextUrl]
  );
  const [promptIdeas, setPromptIdeas] = useState<GroundedStrategicIdea[]>([]);
  const [trackedPrompts, setTrackedPrompts] = useState<TrackedPromptItem[]>([]);
  const [visibilityQueries, setVisibilityQueries] = useState<VisibilityQuery[]>([]);
  const [visibilitySummary, setVisibilitySummary] = useState<VisibilitySummaryResponse | null>(
    null
  );
  const [isGeneratingPrompts, setIsGeneratingPrompts] = useState(false);
  const [promptError, setPromptError] = useState("");
  const [isTrackerLoading, setIsTrackerLoading] = useState(false);
  const [isVisibilityLoading, setIsVisibilityLoading] = useState(false);
  const [activeTrackingKey, setActiveTrackingKey] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(storageKey);
      setTrackedPrompts(normalizeTrackedPrompts(raw ? JSON.parse(raw) : []));
    } catch {
      setTrackedPrompts([]);
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
          `/api/geo/prompt-tracker?context_url=${encodeURIComponent(trackerContextUrl)}`,
          {
            method: "GET",
            headers,
          }
        );
        if (!response.ok) {
          throw new Error("Unable to load tracked prompts from cloud");
        }
        const payload = (await response.json()) as TrackerApiPayload;
        if (cancelled) return;
        const normalized = (payload.items || [])
          .map((item) => {
            if (!item || typeof item.prompt !== "string" || !item.prompt.trim()) return null;
            return {
              prompt: item.prompt.trim(),
              trackedAt:
                typeof item.tracked_at === "string" && item.tracked_at.trim()
                  ? item.tracked_at
                  : new Date().toISOString(),
            } as TrackedPromptItem;
          })
          .filter((item): item is TrackedPromptItem => item !== null);
        setTrackedPrompts(normalized);
      } catch {
        if (!cancelled) {
          setPromptError(
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
    window.localStorage.setItem(storageKey, JSON.stringify(trackedPrompts));
  }, [storageKey, trackedPrompts]);

  useEffect(() => {
    if (!getAuthHeaders) return;

    const timeout = window.setTimeout(async () => {
      try {
        const headers = {
          "Content-Type": "application/json",
          ...(await getAuthHeaders()),
        };
        await fetch("/api/geo/prompt-tracker", {
          method: "PUT",
          headers,
          body: JSON.stringify({
            context_url: trackerContextUrl,
            items: trackedPrompts.map((item) => ({
              prompt: item.prompt,
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
  }, [getAuthHeaders, trackedPrompts, trackerContextUrl]);

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
      setPromptError(
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

  const monitoredPrompts = useMemo(
    () => visibilityQueries.filter((query) => query.query_type === "geo"),
    [visibilityQueries]
  );
  const monitoredPromptMap = useMemo(
    () => new Map(monitoredPrompts.map((query) => [normalizeTrackingKey(query.query_text), query])),
    [monitoredPrompts]
  );
  const monitoredSummaryRows = useMemo(
    () => (visibilitySummary?.queries ?? []).filter((query) => query.query_type === "geo"),
    [visibilitySummary]
  );
  const manualTrackedPrompts = useMemo(
    () =>
      trackedPrompts.filter((item) => !monitoredPromptMap.has(normalizeTrackingKey(item.prompt))),
    [monitoredPromptMap, trackedPrompts]
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
    if (promptIdeas.length > 0) {
      return;
    }

    const fallbackIdeas = [
      ...buildMonitoredPromptIdeas(monitoredSummaryRows),
      ...buildTrackedPromptIdeas(manualTrackedPrompts),
    ];
    if (fallbackIdeas.length === 0) {
      return;
    }

    setPromptIdeas(fallbackIdeas);
  }, [manualTrackedPrompts, monitoredSummaryRows, promptIdeas.length]);

  const saveManualPrompt = useCallback((prompt: string) => {
    const normalized = prompt.trim();
    if (!normalized) return;
    setTrackedPrompts((current) => {
      if (
        current.some(
          (item) => normalizeTrackingKey(item.prompt) === normalizeTrackingKey(normalized)
        )
      ) {
        return current;
      }
      return [
        {
          prompt: normalized,
          trackedAt: new Date().toISOString(),
        },
        ...current,
      ];
    });
  }, []);

  const removeManualPrompt = useCallback((prompt: string) => {
    setTrackedPrompts((current) =>
      current.filter((item) => normalizeTrackingKey(item.prompt) !== normalizeTrackingKey(prompt))
    );
  }, []);

  const enableTracking = useCallback(
    async (prompt: string) => {
      if (!hasProjectMonitoring || !numericProjectId || !getAuthHeaders) {
        saveManualPrompt(prompt);
        return;
      }

      const normalized = prompt.trim();
      if (!normalized) return;

      const trackingKey = normalizeTrackingKey(normalized);
      const existing = monitoredPromptMap.get(trackingKey);

      setActiveTrackingKey(trackingKey);
      setPromptError("");
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
              query_type: "geo",
              providers: monitoringProviders,
            },
            headers
          );
        }
        await loadVisibilityTelemetry();
      } catch (error) {
        setPromptError(
          error instanceof Error
            ? error.message
            : "Unable to enable project monitoring for this prompt."
        );
      } finally {
        setActiveTrackingKey(null);
      }
    },
    [
      getAuthHeaders,
      hasProjectMonitoring,
      loadVisibilityTelemetry,
      monitoredPromptMap,
      monitoringProviders,
      numericProjectId,
      saveManualPrompt,
    ]
  );

  const disableTracking = useCallback(
    async (prompt: string) => {
      const trackingKey = normalizeTrackingKey(prompt);
      const existing = monitoredPromptMap.get(trackingKey);

      if (hasProjectMonitoring && numericProjectId && getAuthHeaders && existing?.is_active) {
        setActiveTrackingKey(trackingKey);
        setPromptError("");
        try {
          const headers = await getAuthHeaders();
          await deleteVisibilityQuery(numericProjectId, existing.id, headers);
          await loadVisibilityTelemetry();
        } catch (error) {
          setPromptError(
            error instanceof Error ? error.message : "Unable to remove monitoring for this prompt."
          );
        } finally {
          setActiveTrackingKey(null);
        }
        return;
      }

      removeManualPrompt(prompt);
    },
    [
      getAuthHeaders,
      hasProjectMonitoring,
      loadVisibilityTelemetry,
      monitoredPromptMap,
      numericProjectId,
      removeManualPrompt,
    ]
  );

  const generatePromptIdeasWithAI = useCallback(async () => {
    setPromptError("");
    setIsGeneratingPrompts(true);

    try {
      if (!auditId) {
        throw new Error("Grounded prompts require a saved audit.");
      }

      const insights = await generateAiStrategicInsights({
        auditId,
        projectId: numericProjectId,
      });
      if (!insights || insights.geo_prompt_ideas.length === 0) {
        throw new Error("No grounded AI visibility prompts were available for this audit yet.");
      }
      setPromptIdeas(insights.geo_prompt_ideas);
    } catch (error) {
      setPromptError(
        error instanceof Error
          ? error.message
          : "Unable to load grounded AI visibility prompt ideas right now."
      );
    } finally {
      setIsGeneratingPrompts(false);
    }
  }, [auditId, numericProjectId]);

  useEffect(() => {
    if (!auditId) {
      return;
    }

    void generatePromptIdeasWithAI();
  }, [auditId, generatePromptIdeasWithAI]);

  if (lockedSection?.is_locked) {
    return (
      <PlanLockNotice
        {...getPlanLockContent("brandIntegrity", {
          requiredPlanLabel: lockedSection.required_plan_label?.trim(),
          title: "AI visibility integrity insights are locked on the current plan",
          description:
            lockedSection.detail?.trim() ||
            "Upgrade this workspace to unlock hallucination detection, claim grounding analysis, and integrity certification for AI visibility reports.",
        })}
        badgeLabel="Locked in API payload"
        align="center"
        className="mx-auto max-w-4xl"
      />
    );
  }

  if (isBrandWithoutUrl) {
    return (
      <div className="space-y-8">
        <div className="rounded-xl border-0 bg-white p-6">
          <h3 className="text-lg font-semibold text-(--t-1)">
            Brand Entity AI Visibility Assessment
          </h3>
          <p className="mt-2 text-sm text-(--t-2)">
            This audit evaluated brand entity signals and search presence rather than website-level
            AI visibility factors like local schema markup and NAP-W completeness. The AI visibility
            score reflects brand citation readiness and entity authority across generative search
            engines.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border-0 bg-white p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              AI Visibility Score
            </div>
            <div className="mt-1 text-2xl font-bold text-(--t-1)">{geoScore}</div>
          </div>
          <div className="rounded-xl border-0 bg-white p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Summary
            </div>
            <p className="mt-1 text-sm text-(--t-2)">
              {geoSummary || "No AI visibility summary available."}
            </p>
          </div>
        </div>

        {geoRecommendations.length > 0 && (
          <div className="rounded-xl border-0 bg-white p-5">
            <h4 className="mb-3 text-sm font-semibold text-(--t-1)">
              Entity Visibility Recommendations
            </h4>
            <ul className="space-y-2">
              {geoRecommendations.map((rec, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-(--t-2)">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  {rec}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-12 pb-12">
      {(() => {
        const scoreColor = getScoreColor(geoScore);

        return (
          <div className="relative group">
            <div className="relative overflow-hidden">
              <div className="relative z-10 flex flex-col gap-10 xl:flex-row xl:items-start xl:justify-between">
                <div className="max-w-xl space-y-6">
                  <div className="space-y-2">
                    <h3 className="flex items-center gap-3 font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
                      <GeoIcon className="h-5 w-5 text-primary" />
                      Generative Engine Optimization
                    </h3>
                    <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      Projection Layer Analysis
                    </p>
                  </div>
                  <p className="rounded-[10px] bg-(--line-2) px-[14px] py-3 text-[12.5px] text-(--t-2)">
                    {geoSummary}
                  </p>
                </div>

                <div className="flex flex-col items-center gap-10 sm:flex-row">
                  <div className="flex flex-col items-center gap-2 sm:items-end">
                    <div className="flex items-baseline gap-1">
                      <div
                        className={cx("text-6xl font-black score-glow", scoreColor.text)}
                        style={
                          { "--score-glow-color": `${scoreColor.hex}40` } as React.CSSProperties
                        }
                      >
                        {Math.round(geoScore)}
                      </div>
                      <span className="text-sm font-black text-(--t-3)">/100</span>
                    </div>
                    <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
                      Global AI Visibility Pulse
                    </div>
                  </div>

                  <div className="hidden h-20 w-px bg-(--line-2) sm:block" />

                  <div className="grid grid-cols-2 gap-x-10 gap-y-4">
                    <div className="space-y-1">
                      <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Trust Signals
                      </div>
                      <div className="font-mono text-lg font-black text-(--t-1)">
                        {geoTabData?.trustSignalsScore ??
                          t("signalAuditReport.entities.notMeasured")}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Citability
                      </div>
                      <div className="font-mono text-lg font-black text-(--t-1)">
                        {geoTabData?.citabilityScore ?? t("signalAuditReport.entities.notMeasured")}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Entity Match
                      </div>
                      <div className="font-mono text-lg font-black text-(--t-1)">
                        {geoTabData?.entityMatchingScore ??
                          t("signalAuditReport.entities.notMeasured")}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Technical
                      </div>
                      <div className="font-mono text-lg font-black text-(--t-1)">
                        {geoTabData?.technicalSeoScore ??
                          t("signalAuditReport.entities.notMeasured")}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {geoRecommendations.length > 0 ? (
        <div className="space-y-8">
          <div className="flex items-center gap-4">
            <h3 className="flex items-center gap-3 font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
              <ChevronRight className="h-4 w-4 text-primary" />
              Optimization Trajectory
            </h3>
            <div className="h-px flex-1 bg-(--line-2)" />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {geoRecommendations.map((rec, i) => (
              <div key={i} className="group relative">
                <div className="relative flex items-start gap-5 overflow-hidden rounded border-0 p-6 transition-all duration-500 hover:border-(--line) hover:bg-(--line-2)">
                  <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border-0 bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                    <Target className="h-4 w-4" />
                  </div>
                  <div className="space-y-1">
                    <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
                      Strategy node {i + 1}
                    </div>
                    <p className="text-[11px] font-bold uppercase tracking-wide text-(--t-2) transition-colors group-hover:text-(--t-1)">
                      {rec}
                    </p>
                  </div>
                  <div className="absolute right-6 top-6 flex items-center gap-2">
                    {(() => {
                      const trackedExport = getTrackedExport(`geo-rec:${rec}`);
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
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="space-y-8">
        <div className="flex items-center gap-4">
          <h3 className="flex items-center gap-3 font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
            <Sparkles className="h-4 w-4 text-primary" />
            Grounded Prompt Radar
          </h3>
          <div className="h-px flex-1 bg-(--line-2)" />
          <Button
            variant="outline"
            size="sm"
            onClick={generatePromptIdeasWithAI}
            disabled={isGeneratingPrompts}
            className="h-9 px-4"
          >
            {isGeneratingPrompts ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Refreshing...
              </>
            ) : (
              "Refresh grounded prompts"
            )}
          </Button>
        </div>

        {promptError ? (
          <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
            {promptError}
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
          <div className="space-y-4 rounded border-0 p-5">
            <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) text-(--t-3)">
              Suggested Prompts
            </p>
            <div className="max-h-[460px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
              {promptIdeas.length === 0 ? (
                <div className="rounded-[10px] bg-(--line-2) px-[14px] py-3 text-[12.5px] text-(--t-2)">
                  No grounded AI visibility prompts are available yet. Use project monitoring to
                  capture measured telemetry or save a manual hypothesis when monitoring is not
                  available.
                </div>
              ) : (
                promptIdeas.map((idea, index) => {
                  const prompt = idea.text;
                  const trackingKey = normalizeTrackingKey(prompt);
                  const monitoredPrompt = monitoredPromptMap.get(trackingKey);
                  const isMonitored = monitoredPrompt?.is_active === true;
                  const isManuallySaved = trackedPrompts.some(
                    (item) => normalizeTrackingKey(item.prompt) === trackingKey
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
                      key={`${prompt}-${index}`}
                      className="rounded-xl border-0 bg-black/30 p-3"
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
                          {prompt}
                        </p>
                        <div className="flex shrink-0 flex-col gap-2">
                          <Button
                            variant={isSelected ? "danger" : "ghost"}
                            size="sm"
                            onClick={() =>
                              void (isSelected ? disableTracking(prompt) : enableTracking(prompt))
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
                    Monitor prompts from the left panel to start measured citation tracking.
                  </div>
                ) : (
                  <div className="max-h-[320px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                    {monitoredSummaryRows.map((item) => {
                      const trackingKey = normalizeTrackingKey(item.query_text);
                      return (
                        <div
                          key={item.id}
                          className="space-y-3 rounded-xl border-0 bg-black/30 p-3"
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

                {manualTrackedPrompts.length > 0 ? (
                  <div className="space-y-3 border-t border-(--line) pt-4">
                    <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      Manual Hypotheses
                    </p>
                    <div className="max-h-[160px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                      {manualTrackedPrompts.map((item) => (
                        <div
                          key={item.prompt}
                          className="space-y-2 rounded-xl border-0 bg-black/30 p-3"
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
                                {item.prompt}
                              </p>
                            </div>
                            <Button
                              variant="danger"
                              size="sm"
                              onClick={() => removeManualPrompt(item.prompt)}
                              aria-label={`Remove manual hypothesis ${item.prompt}`}
                              className="h-7 px-2.5"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                          <p className="text-[10px] text-(--t-2)">{MANUAL_PROMPT_NOTE}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : trackedPrompts.length === 0 ? (
              <div className="rounded-[10px] bg-(--line-2) px-[14px] py-3 text-[12.5px] text-(--t-2)">
                Save prompts from the left panel to keep a manual hypothesis list for later
                validation.
              </div>
            ) : (
              <div className="max-h-[460px] space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                {trackedPrompts.map((item) => (
                  <div
                    key={item.prompt}
                    className="space-y-2 rounded-xl border-0 bg-black/30 p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge color="warning">hypothesis</Badge>
                          <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                            Saved <ClientSafeDate date={item.trackedAt} format="date" />
                          </span>
                        </div>
                        <p className="text-[11px] leading-relaxed text-(--t-1)">{item.prompt}</p>
                      </div>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => removeManualPrompt(item.prompt)}
                        aria-label={`Remove manual hypothesis ${item.prompt}`}
                        className="h-7 px-2.5"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    <p className="text-[10px] text-(--t-2)">{MANUAL_PROMPT_NOTE}</p>
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
