"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, Calendar, Loader2, Pause, Play } from "lucide-react";
import Button from "@/components/ui/Button";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import Card from "@/components/ui/Card";
import SelectField from "@/components/ui/SelectField";
import FeatureLockOverlay from "@/components/dashboard/FeatureLockOverlay";
import { CARD_LABEL_CLASS, CARD_TITLE_CLASS } from "@/components/ui/cardStyleTokens";
import { LABEL_CLASS } from "@/components/ui/typographyTokens";
import { useAuth } from "@/contexts/AuthContext";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import { cx } from "@/components/ui/utils";
import { toast } from "sonner";

type ScheduleFrequency = "weekly" | "monthly";

type ScheduledAuditRecord = {
  id: number;
  url: string;
  project_id?: number | null;
  site_id?: number | null;
  is_active: boolean;
  frequency: ScheduleFrequency;
  next_run_at?: string | null;
  paused_reason?: string | null;
  last_run_status?: string | null;
};

interface ScheduleAutomationProps {
  targetUrl: string;
  projectId?: number | null;
  siteId?: number | null;
  auditParams?: Record<string, unknown>;
  isLocked?: boolean;
  onConfigUpdate?: (config: { isActive: boolean; frequency: ScheduleFrequency }) => void;
  variant?: "default" | "compact";
  className?: string;
  compactLockedMode?: "overlay" | "hidden" | "strip";
}

const FREQUENCY_OPTIONS: Array<{ value: ScheduleFrequency; label: string }> = [
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
];

function normalizeFrequency(value: string | null | undefined): ScheduleFrequency {
  return value === "monthly" ? "monthly" : "weekly";
}

function formatNextRun(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function formatPausedReason(reason: string | null | undefined): string | null {
  if (!reason) {
    return null;
  }
  if (reason === "insufficient_credits") {
    return "Paused automatically by an earlier internal limit.";
  }
  if (reason === "plan_restricted") {
    return "Paused automatically because the current plan no longer supports scheduling.";
  }
  if (reason === "budget_exceeded") {
    return "Paused automatically because this project reached its monthly scan cap. Raise the cap in project settings or wait for the next budget cycle.";
  }
  if (reason === "manual") {
    return "Paused manually.";
  }
  return null;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string") {
      return payload.detail;
    }
    if (typeof payload?.message === "string") {
      return payload.message;
    }
  } catch {
    return `Request failed with status ${response.status}`;
  }
  return `Request failed with status ${response.status}`;
}

export const ScheduleAutomation = ({
  targetUrl,
  projectId,
  siteId,
  auditParams,
  isLocked = false,
  onConfigUpdate,
  variant = "default",
  className,
  compactLockedMode = "overlay",
}: ScheduleAutomationProps) => {
  const { getToken, user, isLoading: authLoading } = useAuth();
  const capabilities = resolvePlanCapabilities(user?.subscription_plan);
  const featureLocked = Boolean(isLocked || (!authLoading && !capabilities.can_schedule_audits));
  const hasTarget =
    (projectId !== null && projectId !== undefined) || (siteId !== null && siteId !== undefined);

  const [scheduleId, setScheduleId] = useState<number | null>(null);
  const [isActive, setIsActive] = useState(false);
  const [frequency, setFrequency] = useState<ScheduleFrequency>("weekly");
  const [persistedConfig, setPersistedConfig] = useState<{
    isActive: boolean;
    frequency: ScheduleFrequency;
  }>({
    isActive: false,
    frequency: "weekly",
  });
  const [nextRunAt, setNextRunAt] = useState<string | null>(null);
  const [pausedReason, setPausedReason] = useState<string | null>(null);
  const [lastRunStatus, setLastRunStatus] = useState<string | null>(null);
  const [isLoadingSchedule, setIsLoadingSchedule] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const applyScheduleState = (schedule: ScheduledAuditRecord | null) => {
    if (!schedule) {
      setScheduleId(null);
      setIsActive(false);
      setFrequency("weekly");
      setNextRunAt(null);
      setPausedReason(null);
      setLastRunStatus(null);
      setPersistedConfig({ isActive: false, frequency: "weekly" });
      return;
    }

    setScheduleId(schedule.id);
    setIsActive(Boolean(schedule.is_active));
    setFrequency(normalizeFrequency(schedule.frequency));
    setNextRunAt(schedule.next_run_at ?? null);
    setPausedReason(schedule.paused_reason ?? null);
    setLastRunStatus(schedule.last_run_status ?? null);
    setPersistedConfig({
      isActive: Boolean(schedule.is_active),
      frequency: normalizeFrequency(schedule.frequency),
    });
  };

  useEffect(() => {
    let cancelled = false;

    async function loadSchedule(): Promise<void> {
      if (!hasTarget) {
        setIsLoadingSchedule(false);
        applyScheduleState(null);
        return;
      }

      setIsLoadingSchedule(true);
      try {
        const token = await getToken();
        const params = new URLSearchParams();
        if (projectId !== null && projectId !== undefined) {
          params.set("project_id", String(projectId));
        }
        if (siteId !== null && siteId !== undefined) {
          params.set("site_id", String(siteId));
        }

        const response = await fetch(`/api/scheduled-audits?${params.toString()}`, {
          method: "GET",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error(await readErrorMessage(response));
        }

        const schedules = (await response.json()) as ScheduledAuditRecord[];
        if (!cancelled) {
          applyScheduleState(
            Array.isArray(schedules) && schedules.length > 0 ? schedules[0] : null
          );
        }
      } catch (error) {
        if (!cancelled && !featureLocked) {
          toast.error("Failed to load automation schedule", {
            description: error instanceof Error ? error.message : "Please try again.",
          });
        }
      } finally {
        if (!cancelled) {
          setIsLoadingSchedule(false);
        }
      }
    }

    if (authLoading) {
      setIsLoadingSchedule(true);
      return () => {
        cancelled = true;
      };
    }

    void loadSchedule();
    return () => {
      cancelled = true;
    };
  }, [authLoading, featureLocked, getToken, hasTarget, projectId, siteId, targetUrl]);

  const saveSchedule = async (
    nextActive: boolean,
    nextFrequency: ScheduleFrequency,
    previousState: { isActive: boolean; frequency: ScheduleFrequency }
  ) => {
    if (!hasTarget || featureLocked) {
      return;
    }

    setIsSaving(true);
    try {
      const token = await getToken();
      const payload: Record<string, unknown> = {
        url: targetUrl,
        frequency: nextFrequency,
        is_active: nextActive,
      };
      if (projectId !== null && projectId !== undefined) {
        payload.project_id = projectId;
      }
      if (siteId !== null && siteId !== undefined) {
        payload.site_id = siteId;
      }
      if (auditParams && Object.keys(auditParams).length > 0) {
        payload.audit_params = auditParams;
      }

      const response = await fetch(
        scheduleId !== null ? `/api/scheduled-audits/${scheduleId}` : "/api/scheduled-audits",
        {
          method: scheduleId !== null ? "PATCH" : "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }

      const schedule = (await response.json()) as ScheduledAuditRecord;
      applyScheduleState(schedule);
      onConfigUpdate?.({
        isActive: Boolean(schedule.is_active),
        frequency: normalizeFrequency(schedule.frequency),
      });
      toast.success(schedule.is_active ? "Automation enabled" : "Automation paused", {
        description: schedule.is_active
          ? `This audit will run automatically on a ${normalizeFrequency(schedule.frequency)} cadence.`
          : "The recurring assessment has been paused.",
      });
    } catch (error) {
      setIsActive(previousState.isActive);
      setFrequency(previousState.frequency);
      toast.error("Failed to update automation schedule", {
        description: error instanceof Error ? error.message : "Please try again.",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggle = async (checked: boolean) => {
    const previousState = { isActive, frequency };
    setIsActive(checked);
    if (variant === "compact") {
      await saveSchedule(checked, frequency, previousState);
    }
  };

  const handleFrequencyChange = async (value: string) => {
    const nextFrequency = normalizeFrequency(value);
    const previousState = { isActive, frequency };
    setFrequency(nextFrequency);
    if (variant === "compact" && (scheduleId !== null || isActive)) {
      await saveSchedule(isActive, nextFrequency, previousState);
    }
  };

  const handleSaveClick = async () => {
    await saveSchedule(isActive, frequency, persistedConfig);
  };

  const nextRunLabel = formatNextRun(nextRunAt);
  const pausedReasonLabel = formatPausedReason(pausedReason);
  const showUnavailableState = !hasTarget;
  const controlsDisabled =
    featureLocked || showUnavailableState || isLoadingSchedule || authLoading;
  const unavailableCompactCopy = "Link this audit to a project to enable weekly or monthly runs.";
  const unavailableDetailedCopy =
    "Recurring audits require a linked project. Attach this audit to a project first, then choose a weekly or monthly schedule.";

  if (variant === "compact") {
    if (featureLocked && compactLockedMode === "hidden") {
      return null;
    }

    return (
      <div className={cx("relative h-12 max-md:h-auto", className)}>
        {featureLocked && compactLockedMode !== "strip" && (
          <FeatureLockOverlay
            title="Automated Scheduled Assessments"
            description="Unlock scheduled background automation."
            ctaLabel="Upgrade to Specialist"
            href="/dashboard/billing"
          />
        )}
        <div
          className={cx(
            "flex h-full items-center gap-4 px-1 transition-colors max-md:flex-wrap max-md:py-3",
            compactLockedMode === "strip" ? "bg-transparent" : "surface-panel rounded-md px-4",
            featureLocked &&
              compactLockedMode !== "strip" &&
              "pointer-events-none select-none opacity-50 blur-xs"
          )}
        >
          <div className="flex shrink-0 items-center gap-2">
            <Calendar className="h-3.5 w-3.5 text-primary" />
            <span className={CARD_LABEL_CLASS}>Recurring audits</span>
          </div>

          <div className="h-5 w-px shrink-0 bg-(--border)" />

          {showUnavailableState ? (
            <span className="text-xs text-(--text-muted)">{unavailableCompactCopy}</span>
          ) : isLoadingSchedule ? (
            <div className="flex items-center gap-2 text-xs text-(--text-muted)">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading...
            </div>
          ) : (
            <div className="flex min-w-0 items-center gap-3 max-md:w-full">
              <div className="w-[140px] max-md:flex-1">
                <SelectField
                  aria-label="Recurring audit frequency"
                  value={frequency}
                  onChange={(event) => void handleFrequencyChange(event.target.value)}
                  disabled={controlsDisabled || (!isActive && scheduleId === null) || isSaving}
                  className="h-9 px-3 py-0 text-xs"
                >
                  {FREQUENCY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </SelectField>
              </div>

              <ToggleSwitch
                checked={isActive}
                onChange={(checked) => void handleToggle(checked)}
                aria-label="Recurring audits"
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  const internalContent = (
    <Card className="flex h-full flex-col overflow-hidden">
      <div className="border-b border-(--border) p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
              <Calendar className="h-5 w-5" />
            </div>
            <div>
              <p className={CARD_LABEL_CLASS}>Recurring audits</p>
              <h3 className={cx("mt-2", CARD_TITLE_CLASS)}>Automated scheduled assessments</h3>
              <p className={cx("mt-2 max-w-2xl", LABEL_CLASS)}>
                Run recurring audits automatically on a weekly or monthly cadence.
              </p>
            </div>
          </div>
          <ToggleSwitch
            checked={isActive}
            onChange={(checked) => void handleToggle(checked)}
            aria-label="Automated scheduled assessments"
          />
        </div>
      </div>

      <div className="space-y-6 p-6">
        {showUnavailableState ? (
          <div className="rounded-md border border-(--border) bg-(--surface-subtle) p-5 text-sm text-(--text-soft)">
            {unavailableDetailedCopy}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className={cx("transition-opacity", !isActive && "opacity-60")}>
                <SelectField
                  label="Frequency"
                  value={frequency}
                  onChange={(event) => void handleFrequencyChange(event.target.value)}
                  disabled={controlsDisabled || isSaving}
                >
                  {FREQUENCY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </SelectField>
              </div>

              <div className="rounded-md border border-warning/25 bg-warning/10 p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                  <div className="space-y-1">
                    <h4 className="text-sm font-semibold text-warning">Scan usage</h4>
                    <p className="text-sm leading-6 text-warning/80">
                      Each run of this recurring audit counts as one scan against your plan
                      allowance.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-md border border-(--border) bg-(--surface-subtle) px-4 py-3 text-sm text-(--text-soft)">
              {isLoadingSchedule ? (
                <div className="flex items-center gap-2 text-(--text-muted)">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading schedule state...
                </div>
              ) : nextRunLabel && isActive ? (
                <p>
                  Next run:{" "}
                  <span className="font-semibold text-(--foreground)">{nextRunLabel}</span>
                </p>
              ) : (
                <p>No active recurring schedule is configured yet.</p>
              )}
              {pausedReasonLabel ? <p className="mt-1 text-warning">{pausedReasonLabel}</p> : null}
              {lastRunStatus === "failed" && !pausedReasonLabel ? (
                <p className="mt-1 text-danger">
                  The last scheduled run failed. The next run will continue automatically.
                </p>
              ) : null}
            </div>
          </>
        )}
      </div>

      <div className="flex items-center justify-between gap-4 border-t border-(--border) bg-(--surface-subtle) px-6 py-4">
        <div className="flex items-center text-sm text-(--text-muted)">
          {isActive ? (
            <>
              <Play className="mr-2 h-4 w-4 text-primary" />
              Active
            </>
          ) : (
            <>
              <Pause className="mr-2 h-4 w-4 text-(--text-muted)" />
              Paused
            </>
          )}
        </div>
        <Button
          onClick={() => void handleSaveClick()}
          disabled={controlsDisabled || isSaving}
          variant="outline"
        >
          {isSaving ? "Saving..." : scheduleId !== null ? "Update schedule" : "Save schedule"}
        </Button>
      </div>
    </Card>
  );

  return (
    <div className={cx("relative", className)}>
      {featureLocked && (
        <FeatureLockOverlay
          title="Automated Scheduled Assessments"
          description="Unlock scheduled background automation to proactively monitor algorithm updates."
          ctaLabel="Upgrade to Specialist"
          href="/dashboard/billing"
        />
      )}
      <div
        className={`transition-all duration-500 ${featureLocked ? "blur-xs opacity-50 select-none pointer-events-none" : ""}`}
      >
        {internalContent}
      </div>
    </div>
  );
};
