"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Bell, Loader2, Plus, RefreshCcw, Trash2 } from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import FeatureLockOverlay from "@/components/dashboard/FeatureLockOverlay";
import { ScoreMetricTile } from "@/components/dashboard/scorePrimitives";
import PageLoaderOverlay from "@/components/ui/PageLoaderOverlay";
import { cx } from "@/components/ui/utils";
import { formatDateTime, formatRelativeTime } from "@/lib/dateFormat";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import {
  createProjectCompetitor,
  deleteProjectCompetitor,
  fetchProjectById,
  fetchProjectCompetitors,
  type CompetitiveDigestFrequency,
  type ProjectCompetitorListItem,
  updateProjectById,
} from "@/services/workspaceService";

const COMPETITOR_LIMIT = 5;

const DIGEST_OPTIONS: Array<{
  value: CompetitiveDigestFrequency;
  label: string;
  help: string;
}> = [
  {
    value: "off",
    label: "Off",
    help: "Disable recurring benchmark digest emails for this project.",
  },
  {
    value: "weekly",
    label: "Weekly",
    help: "Send a weekly benchmark digest after scheduled competitor runs settle.",
  },
  {
    value: "monthly",
    label: "Monthly",
    help: "Roll benchmark movement into a lighter monthly digest.",
  },
];

const STATUS_STYLES: Record<
  ProjectCompetitorListItem["latest_status"],
  { label: string; className: string }
> = {
  not_started: {
    label: "Not Benchmarked",
    className: "border-(--border) bg-(--surface-subtle) text-(--text-soft)",
  },
  pending: {
    label: "Queued",
    className: "border-warning/25 bg-warning/10 text-warning",
  },
  failed: {
    label: "Failed",
    className: "border-danger/25 bg-danger/10 text-danger",
  },
  succeeded: {
    label: "Ready",
    className: "border-success/25 bg-success/10 text-success",
  },
};

const formatScore = (value: number | null) =>
  typeof value === "number" ? Math.round(value) : "--";

type ProjectCompetitorManagerProps = {
  projectId: string;
  /** Set false when the surrounding card renders the lock over the whole
      section, heading included, instead of this card alone. */
  showPlanLockOverlay?: boolean;
};

export function ProjectCompetitorManager({
  projectId,
  showPlanLockOverlay = true,
}: ProjectCompetitorManagerProps) {
  const { getToken, isLoading: authLoading, isSignedIn, user } = useAuth();
  const capabilities = resolvePlanCapabilities(user?.subscription_plan);
  const planLocked = !capabilities.has_competitor_analysis;

  const [loading, setLoading] = useState(true);
  const [savingAutomation, setSavingAutomation] = useState(false);
  const [savingCompetitor, setSavingCompetitor] = useState(false);
  const [removingCompetitorId, setRemovingCompetitorId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [competitors, setCompetitors] = useState<ProjectCompetitorListItem[]>([]);
  const [autoAuditsEnabled, setAutoAuditsEnabled] = useState(true);
  const [digestFrequency, setDigestFrequency] = useState<CompetitiveDigestFrequency>("weekly");
  const [targetUrl, setTargetUrl] = useState("");
  const [displayName, setDisplayName] = useState("");

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to manage competitor benchmarks.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadData = useCallback(async () => {
    if (!projectId || authLoading) {
      return;
    }
    if (!isSignedIn || planLocked) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const [project, competitorRows] = await Promise.all([
        fetchProjectById(projectId, headers),
        fetchProjectCompetitors(projectId, headers),
      ]);
      setAutoAuditsEnabled(project.auto_competitor_audits_enabled ?? true);
      setDigestFrequency(project.competitive_digest_frequency ?? "weekly");
      setCompetitors(competitorRows);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Unable to load competitor benchmark settings."
      );
    } finally {
      setLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, planLocked, projectId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const selectedDigestHelp = useMemo(
    () => DIGEST_OPTIONS.find((option) => option.value === digestFrequency)?.help ?? null,
    [digestFrequency]
  );

  const isBusy = savingAutomation || savingCompetitor || removingCompetitorId !== null;

  const handleSaveAutomation = async () => {
    if (!projectId) {
      return;
    }

    setSavingAutomation(true);
    setFeedback(null);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      await updateProjectById(
        projectId,
        {
          auto_competitor_audits_enabled: autoAuditsEnabled,
          competitive_digest_frequency: digestFrequency,
        },
        headers
      );
      setFeedback("Competitive automation preferences saved.");
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : "Unable to save competitor benchmark settings."
      );
    } finally {
      setSavingAutomation(false);
    }
  };

  const handleAddCompetitor = async () => {
    if (!projectId) {
      return;
    }
    if (!targetUrl.trim()) {
      setError("Enter a competitor domain before adding it to this benchmark set.");
      return;
    }

    setSavingCompetitor(true);
    setFeedback(null);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      await createProjectCompetitor(
        projectId,
        {
          target_url: targetUrl.trim(),
          display_name: displayName.trim() || null,
        },
        headers
      );
      setTargetUrl("");
      setDisplayName("");
      setFeedback("Competitor added to the benchmark roster.");
      await loadData();
    } catch (createError) {
      setError(
        createError instanceof Error
          ? createError.message
          : "Unable to add competitor benchmark target."
      );
    } finally {
      setSavingCompetitor(false);
    }
  };

  const handleRemoveCompetitor = async (competitorId: number) => {
    if (!projectId) {
      return;
    }

    setRemovingCompetitorId(competitorId);
    setFeedback(null);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      await deleteProjectCompetitor(projectId, competitorId, headers);
      setFeedback("Competitor removed from this benchmark set.");
      await loadData();
    } catch (removeError) {
      setError(
        removeError instanceof Error
          ? removeError.message
          : "Unable to remove competitor benchmark target."
      );
    } finally {
      setRemovingCompetitorId(null);
    }
  };

  const shellCls = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";

  if (authLoading || loading) {
    return (
      <section className={shellCls}>
        <div className="flex items-center gap-3 text-[13px] text-(--t-3)">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading competitive benchmark settings...
        </div>
      </section>
    );
  }

  if (!isSignedIn) {
    return (
      <section className={shellCls}>
        <p className="m-0 text-[13px] text-(--t-3)">
          Sign in to manage competitor benchmark targets, automation, and competitive digests.
        </p>
      </section>
    );
  }

  return (
    <section
      id="competitive-intelligence"
      className={`${shellCls} relative overflow-hidden`}
      data-testid="competitive-intelligence-card"
    >
      {planLocked && showPlanLockOverlay ? (
        <FeatureLockOverlay
          title="Competitive Intelligence requires Specialist"
          description="Upgrade this workspace to configure live benchmark targets, recurring competitor assessments, and AI-backed competitive gap summaries."
          ctaLabel="Upgrade workspace"
          className="rounded-(--r)"
        />
      ) : null}

      <PageLoaderOverlay
        detail="Saving benchmark rules and synchronizing the latest competitor roster."
        label="Updating competitive intelligence"
        loading={Boolean(!planLocked && isBusy)}
        overlayClassName="rounded-[inherit]"
      >
        <div className={cx(planLocked && "pointer-events-none select-none blur-[1px]")}>
          {/* Approved `.wsec` card head: wh title, wd description, chip +
              dashboard action at the row end. */}
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                Competitive Intelligence
              </h3>
              <p className="mt-1 text-[12.5px] leading-[1.5] text-(--t-3)">
                Benchmark the client against the real market set. Add up to five competitor domains
                and control benchmark cadence.
              </p>
            </div>
            <div className="flex flex-none items-center gap-3">
              <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
                {competitors.length}/{COMPETITOR_LIMIT} active targets
              </span>
              <Link
                href={`/dashboard/projects/${projectId}/competitors`}
                className="inline-flex h-8 items-center gap-1.5 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] max-md:min-h-11"
              >
                Open dashboard
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>

          {/* Automation sub-block */}
          <div className="mt-4 border-t border-t-(--line-2) pt-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[13.5px] font-semibold">
                  Auto-run competitor benchmarks after each scheduled audit
                </div>
                <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
                  Each scheduled audit spawns FAST benchmark runs for the configured competitor set
                  and feeds the competitive dashboard automatically.
                </div>
              </div>
              {/* Approved `.switchT`: 42x24 on pill, 44px touch zone on mobile. */}
              <button
                type="button"
                role="switch"
                aria-checked={autoAuditsEnabled}
                aria-label="Auto-run competitor benchmarks after each scheduled audit"
                className="inline-flex flex-none cursor-pointer items-center justify-center border-none bg-transparent p-0 max-md:min-h-11 max-md:min-w-11 ltr:[direction:ltr]"
                onClick={() => setAutoAuditsEnabled((current) => !current)}
              >
                <span
                  className={cx(
                    "relative block h-6 w-[42px] rounded-full transition-colors",
                    autoAuditsEnabled ? "bg-(--good)" : "bg-(--line)"
                  )}
                >
                  <span
                    className={cx(
                      "absolute top-[3px] block h-[18px] w-[18px] rounded-full bg-white transition-[left]",
                      autoAuditsEnabled ? "left-[21px]" : "left-[3px]"
                    )}
                  />
                </span>
              </button>
            </div>

            <div className="mt-3">
              <span
                className="mb-2 block font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                id="competitive-digest-frequency-label"
              >
                Competitive digest frequency
              </span>
              {/* Approved `.seg` group: Off / Weekly / Monthly. */}
              <div
                className="inline-flex gap-[2px] rounded-[9px] border-0 bg-[#EEF1F6] p-[3px] ltr:[direction:ltr]"
                role="group"
                aria-labelledby="competitive-digest-frequency-label"
              >
                {DIGEST_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={digestFrequency === option.value}
                    className={cx(
                      "cursor-pointer rounded-[6px] border-none px-3 py-1.5 font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-2) max-md:min-h-11",
                      digestFrequency === option.value && "bg-(--ink) text-white"
                    )}
                    onClick={() => setDigestFrequency(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              {selectedDigestHelp ? (
                <p className="mt-2 flex items-start gap-1.5 text-[12px] leading-[1.45] text-(--t-3)">
                  <Bell className="mt-px h-3.5 w-3.5 flex-none" />
                  {selectedDigestHelp}
                </p>
              ) : null}
            </div>

            <div className="mt-3.5 flex flex-wrap items-center justify-end gap-3">
              <span className="mr-auto flex items-center gap-1.5 text-[12px] text-(--t-3)">
                <RefreshCcw className="h-3.5 w-3.5" />
                Benchmark refreshes remain available from the Competitive tab.
              </span>
              <button
                type="button"
                className="inline-flex h-[38px] cursor-pointer items-center rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-50 max-md:min-h-11"
                onClick={() => void handleSaveAutomation()}
                disabled={savingAutomation}
              >
                {savingAutomation ? "Saving..." : "Save Automation"}
              </button>
            </div>
          </div>

          {/* Benchmark Roster sub-block */}
          <div className="mt-4 border-t border-t-(--line-2) pt-4">
            <div className="text-[13.5px] font-semibold">Benchmark Roster</div>
            <div className="mt-0.5 mb-3 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Add the domains the client expects to beat. Maximum {COMPETITOR_LIMIT} competitors per
              project.
            </div>

            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[200px] flex-1">
                <label
                  className="mb-2 block font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                  htmlFor="competitor-target-url"
                >
                  Competitor domain
                </label>
                <input
                  id="competitor-target-url"
                  className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
                  type="text"
                  placeholder="competitor.com"
                  value={targetUrl}
                  disabled={savingCompetitor || competitors.length >= COMPETITOR_LIMIT}
                  onChange={(event) => setTargetUrl(event.target.value)}
                />
              </div>
              <div className="min-w-[160px] flex-1">
                <label
                  className="mb-2 block font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                  htmlFor="competitor-display-name"
                >
                  Label (optional)
                </label>
                <input
                  id="competitor-display-name"
                  className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
                  type="text"
                  placeholder="Main rival"
                  value={displayName}
                  disabled={savingCompetitor || competitors.length >= COMPETITOR_LIMIT}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </div>
              <button
                type="button"
                className="inline-flex h-[38px] flex-none cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-50 max-md:min-h-11"
                disabled={competitors.length >= COMPETITOR_LIMIT || savingCompetitor}
                onClick={() => void handleAddCompetitor()}
              >
                <Plus className="h-4 w-4" />
                {savingCompetitor ? "Adding..." : "Add Target"}
              </button>
            </div>

            {feedback ? (
              <p className="mt-3 text-[12px] text-(--good)" role="status">
                {feedback}
              </p>
            ) : null}
            {error ? (
              <p className="mt-3 text-[12px] text-(--bad)" role="alert">
                {error}
              </p>
            ) : null}

            {competitors.length === 0 ? (
              <div className="mt-3 rounded-[14px] border border-dashed border-[#D1D5DB] bg-[#F8FAFC] px-4 py-[26px] text-center text-[13px] text-(--t-3)">
                No competitor targets yet.
              </div>
            ) : (
              <div className="mt-3 space-y-3">
                {competitors.map((competitor) => {
                  const statusUi = STATUS_STYLES[competitor.latest_status];
                  return (
                    <div
                      key={competitor.id}
                      className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4"
                    >
                      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                        <div className="min-w-0 space-y-2">
                          <div className="flex flex-wrap items-center gap-2.5">
                            <span className="text-[13.5px] font-semibold text-(--t-1)">
                              {competitor.display_name}
                            </span>
                            <span
                              className={cx(
                                "rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em]",
                                statusUi.className
                              )}
                            >
                              {statusUi.label}
                            </span>
                          </div>
                          <p className="m-0 break-all font-mono text-[11.5px] text-(--t-3)">
                            {competitor.target_url}
                          </p>
                          <p className="m-0 text-[12px] text-(--t-3)">
                            {competitor.last_benchmarked_at
                              ? `Last benchmarked ${formatRelativeTime(competitor.last_benchmarked_at)} (${formatDateTime(competitor.last_benchmarked_at)})`
                              : "No completed benchmark yet."}
                          </p>
                          {competitor.latest_failure_reason ? (
                            <p className="m-0 text-[12px] text-(--bad)">
                              {competitor.latest_failure_reason}
                            </p>
                          ) : null}
                        </div>

                        <div className="grid gap-3 sm:grid-cols-2 xl:min-w-[360px] xl:grid-cols-4">
                          {(["geo", "seo", "aeo", "overall"] as const).map((metric) => (
                            <ScoreMetricTile
                              key={metric}
                              label={metric.toUpperCase()}
                              value={formatScore(competitor.latest_scores[metric])}
                            />
                          ))}
                        </div>
                      </div>

                      <div className="mt-3 flex justify-end">
                        <button
                          type="button"
                          aria-label={`Remove ${competitor.display_name}`}
                          className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#FEECEC] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--bad) disabled:cursor-not-allowed disabled:opacity-50 max-md:min-h-11"
                          disabled={removingCompetitorId === competitor.id}
                          onClick={() => void handleRemoveCompetitor(competitor.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                          {removingCompetitorId === competitor.id ? "Removing..." : "Remove target"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </PageLoaderOverlay>
    </section>
  );
}

export default ProjectCompetitorManager;
