"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React from "react";
import { CalendarRange, Loader2 } from "lucide-react";

import { GlassCard } from "@/components/ui/GlassComponents";
import Button from "@/components/ui/Button";
import CyberField from "@/components/ui/CyberField";
import SelectField from "@/components/ui/SelectField";
import { cx } from "@/components/ui/utils";
import type { ProjectBudgetSummary } from "@/services/workspaceService";

type ProjectBudgetGuardrailCardProps = {
  budget: ProjectBudgetSummary | null;
  isLoading: boolean;
  error: string | null;
  message: string | null;
  disabled?: boolean;
  isSaving: boolean;
  limitInput: string;
  cycleAnchorDay: number;
  onLimitInputChange: (value: string) => void;
  onCycleAnchorDayChange: (value: number) => void;
  onSave: () => void;
  onRemove: () => void;
};

const STATUS_STYLES = {
  unlimited: "border-(--line) bg-(--line-2) text-(--t-2)",
  healthy: "border-(--good)/40 bg-(--good)/10 text-(--good)",
  warning: "border-(--warn)/40 bg-(--warn)/10 text-(--warn)",
  exhausted: "border-(--bad)/40 bg-(--bad)/10 text-(--bad)",
} as const;

const STATUS_LABELS = {
  unlimited: "Unlimited",
  healthy: "Healthy",
  warning: "Warning",
  exhausted: "Cap Reached",
} as const;

const CYCLE_ANCHOR_DAYS = [1, 2, 15, 28] as const;

function formatShortDate(value: string | null | undefined): string {
  if (!value) {
    return "N/A";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "N/A";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(parsed);
}

function formatRange(start: string | null | undefined, end: string | null | undefined): string {
  return `${formatShortDate(start)} - ${formatShortDate(end)}`;
}

function clampProgress(value: number | null | undefined): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

export function ProjectBudgetGuardrailCard({
  budget,
  isLoading,
  error,
  message,
  disabled = false,
  isSaving,
  limitInput,
  cycleAnchorDay,
  onLimitInputChange,
  onCycleAnchorDayChange,
  onSave,
  onRemove,
}: ProjectBudgetGuardrailCardProps) {
  const status = budget?.status ?? "unlimited";
  const progressValue = clampProgress(budget?.percent_consumed);
  const limitLabel =
    budget?.monthly_limit_scans === null || budget?.monthly_limit_scans === undefined
      ? "No cap"
      : `${budget.monthly_limit_scans.toLocaleString()} scans`;
  const remainingLabel =
    budget?.remaining_scans === null || budget?.remaining_scans === undefined
      ? "Unlimited"
      : `${budget.remaining_scans.toLocaleString()} scans`;
  const history = budget?.recent_periods ?? [];

  return (
    <GlassCard className="rounded-(--r) border-(--line) bg-(--panel) px-[22px] py-[18px]">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="text-[15px] font-bold text-(--t-1)">Budget Guardrails</h3>
          <p className="mt-1 max-w-2xl text-[12.5px] leading-6 text-(--t-2)">
            Set a hard monthly scan cap for this project. Manual runs block at the cap and scheduled
            assessments pause automatically until the next budget cycle.
          </p>
        </div>

        <div
          className={cx(
            "inline-flex h-8 shrink-0 items-center justify-center rounded-full border px-3.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em]",
            STATUS_STYLES[status]
          )}
        >
          {STATUS_LABELS[status]}
        </div>
      </div>

      {isLoading ? (
        <div className="mt-6 flex min-h-[160px] flex-col items-center justify-center gap-3 rounded-(--r-sm) border border-(--line) bg-(--line-2)">
          <Loader2 className="h-6 w-6 animate-spin text-(--t-3)" />
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
            Loading budget guardrail
          </p>
        </div>
      ) : (
        <div className="mt-6 space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-(--r-sm) border border-(--line) bg-(--line-2) px-4 py-3.5">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                Current Cycle
              </p>
              <p className="mt-2 text-[15px] font-bold tabular-nums text-(--t-1)">
                {formatRange(budget?.current_period_start, budget?.current_period_end)}
              </p>
            </div>
            <div className="rounded-(--r-sm) border border-(--line) bg-(--line-2) px-4 py-3.5">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                Monthly Cap
              </p>
              <p className="mt-2 text-[15px] font-bold tabular-nums text-(--t-1)">{limitLabel}</p>
            </div>
            <div className="rounded-(--r-sm) border border-(--line) bg-(--line-2) px-4 py-3.5">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                Used
              </p>
              <p className="mt-2 text-[15px] font-bold tabular-nums text-(--t-1)">
                {(budget?.consumed_scans ?? 0).toLocaleString()} scans
              </p>
            </div>
            <div className="rounded-(--r-sm) border border-(--line) bg-(--line-2) px-4 py-3.5">
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                Remaining
              </p>
              <p className="mt-2 text-[15px] font-bold tabular-nums text-(--t-1)">
                {remainingLabel}
              </p>
            </div>
          </div>

          <div className="rounded-(--r-sm) border border-(--line) bg-(--line-2) p-4">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div className="space-y-1">
                <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                  Burn Rate
                </p>
                <p className="text-[12.5px] text-(--t-2)">
                  {budget?.budget_configured
                    ? `${progressValue.toFixed(0)}% of the project cap is already consumed this cycle.`
                    : "No project cap is active. Usage is tracked for reporting only."}
                </p>
              </div>
              <div className="inline-flex items-center gap-2 text-[12px] text-(--t-2)">
                <CalendarRange className="h-4 w-4 text-(--t-3)" />
                Anchor day {budget?.cycle_anchor_day ?? cycleAnchorDay}
              </div>
            </div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-(--line)">
              <div
                className={cx(
                  "h-full w-(--bw) rounded-full transition-all",
                  status === "exhausted"
                    ? "bg-(--bad)"
                    : status === "warning"
                      ? "bg-(--warn)"
                      : "bg-(--good)"
                )}
                style={
                  {
                    "--bw": `${budget?.budget_configured ? progressValue : 8}%`,
                  } as React.CSSProperties
                }
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_220px_auto]">
            <CyberField
              id="project-budget-limit"
              label="Monthly Scan Cap"
              type="number"
              min={0}
              step={1}
              value={limitInput}
              onChange={(event) => onLimitInputChange(event.target.value)}
              disabled={disabled || isSaving}
              placeholder="e.g. 2000 (blank = unlimited)"
            />

            <div className="flex flex-col gap-1.5 pt-1">
              <label className="ml-1 text-[10px] font-black uppercase tracking-[0.2em] text-(--t-3)">
                Cycle Anchor Day
              </label>
              <SelectField
                aria-label="Cycle anchor day"
                value={String(cycleAnchorDay)}
                onChange={(event) => onCycleAnchorDayChange(Number(event.target.value))}
                disabled={disabled || isSaving}
                className="h-11 border-(--line) bg-(--line-2) px-4 py-0 text-sm text-(--t-1)"
              >
                {CYCLE_ANCHOR_DAYS.map((day) => (
                  <option key={day} value={day}>
                    Day {day}
                  </option>
                ))}
              </SelectField>
            </div>

            <div className="flex flex-col gap-3 md:justify-end md:pb-0.5">
              <Button
                variant="primary"
                onClick={onSave}
                disabled={
                  disabled || isSaving || (!limitInput.trim() && !budget?.budget_configured)
                }
                className="h-[38px] px-[15px] max-md:min-h-11"
              >
                {isSaving ? "Saving..." : "Save Cap"}
              </Button>
              <Button
                variant="danger"
                onClick={onRemove}
                disabled={disabled || isSaving || !budget?.budget_configured}
                className="h-[38px] px-[15px] max-md:min-h-11"
              >
                Remove Cap
              </Button>
            </div>
          </div>

          {error ? (
            <SignalAlert tone="danger" title="Budget update failed">
              {error}
            </SignalAlert>
          ) : null}
          {message ? (
            <SignalAlert tone="success" title="Budget updated">
              {message}
            </SignalAlert>
          ) : null}

          <div className="space-y-3">
            <div>
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                Recent Usage Periods
              </p>
              <p className="mt-1.5 text-[12.5px] text-(--t-2)">
                Review monthly usage history and identify cycles that repeatedly hit the cap.
              </p>
            </div>

            {history.length > 0 ? (
              <div className="grid gap-3 lg:grid-cols-2">
                {history.map((period) => (
                  <div
                    key={`${period.period_start}-${period.period_end}`}
                    className="rounded-(--r-sm) border border-(--line) bg-(--line-2) px-4 py-3.5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-[13.5px] font-semibold text-(--t-1)">
                          {formatRange(period.period_start, period.period_end)}
                        </p>
                        <p className="mt-1 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                          Anchor day {period.cycle_anchor_day}
                        </p>
                      </div>
                      <div
                        className={cx(
                          "inline-flex rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em]",
                          STATUS_STYLES[period.status]
                        )}
                      >
                        {STATUS_LABELS[period.status]}
                      </div>
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-3 text-[12.5px]">
                      <div>
                        <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                          Cap
                        </p>
                        <p className="mt-1 tabular-nums text-(--t-1)">
                          {period.budget_limit_scans === null
                            ? "None"
                            : period.budget_limit_scans.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                          Used
                        </p>
                        <p className="mt-1 tabular-nums text-(--t-1)">
                          {period.consumed_scans.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
                          Remaining
                        </p>
                        <p className="mt-1 tabular-nums text-(--t-1)">
                          {period.remaining_scans === null
                            ? "Unlimited"
                            : period.remaining_scans.toLocaleString()}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-(--r-sm) border border-dashed border-(--line) bg-(--line-2) p-5 text-[12.5px] text-(--t-2)">
                No budget history yet. Usage periods populate after the first billable audit for
                this project.
              </div>
            )}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
