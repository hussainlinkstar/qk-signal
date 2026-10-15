import React, { type ReactNode } from "react";
import { AlertCircle, type LucideIcon } from "lucide-react";

import EmptyState from "@/components/ui/EmptyState";
import { GlassCard } from "@/components/ui/GlassComponents";
import { Spinner } from "@/components/ui/Loading";
import { cx } from "@/components/ui/utils";

type MonitoringTone = "slate" | "rose" | "amber";

type ProjectMonitoringSectionProps = {
  id?: string;
  icon: LucideIcon;
  title: string;
  accent: string;
  description: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
};

type ProjectMonitoringStateCardProps = {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  action?: ReactNode;
  tone?: MonitoringTone;
  className?: string;
};

type ProjectMonitoringAlertProps = {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  tone?: MonitoringTone;
  className?: string;
};

type ProjectMonitoringEmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
};

type ProjectMonitoringMetricCardProps = {
  label: string;
  value: ReactNode;
  meta?: ReactNode;
  className?: string;
};

type ProjectMonitoringWidgetCardProps = {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  headerAside?: ReactNode;
  children: ReactNode;
  className?: string;
  iconShellClassName?: string;
  iconClassName?: string;
};

type ProjectMonitoringWidgetInlineErrorProps = {
  message: ReactNode;
  tone?: "amber" | "rose";
  className?: string;
};

type ProjectMonitoringWidgetEmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  className?: string;
};

const toneStyles: Record<
  MonitoringTone,
  {
    card: string;
    header: string;
    body: string;
  }
> = {
  slate: {
    card: "border-(--line) bg-(--line-2)",
    header: "text-(--t-1)",
    body: "text-(--t-2)",
  },
  rose: {
    card: "border-rose-500/30 bg-rose-500/10",
    header: "text-rose-100",
    body: "text-rose-100/90",
  },
  amber: {
    card: "border-amber-400/30 bg-amber-500/10",
    header: "text-amber-100",
    body: "text-amber-100/90",
  },
};

export default function ProjectMonitoringSection({
  id,
  icon: Icon,
  title,
  accent,
  description,
  action,
  children,
  className,
}: ProjectMonitoringSectionProps) {
  return (
    <section id={id} className={cx("space-y-6", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border-0 bg-primary/10 text-primary">
              <Icon className="h-5 w-5" />
            </div>
            <h2 className="text-2xl font-black uppercase tracking-tight text-(--t-1)">
              {title} <span className="text-primary">{accent}</span>
            </h2>
          </div>
          <p className="max-w-3xl text-sm text-(--t-2)">{description}</p>
        </div>
        {action}
      </div>

      {children}
    </section>
  );
}

export function ProjectMonitoringLoadingState({ label }: { label: string }) {
  return (
    <GlassCard className="p-10">
      <Spinner label={label} size="lg" />
    </GlassCard>
  );
}

export function ProjectMonitoringStateCard({
  icon: Icon,
  title,
  description,
  action,
  tone = "slate",
  className,
}: ProjectMonitoringStateCardProps) {
  const toneStyle = toneStyles[tone];

  return (
    <GlassCard className={cx("space-y-4 p-8", toneStyle.card, className)}>
      <div className={cx("flex items-center gap-3", toneStyle.header)}>
        <Icon className="h-5 w-5" />
        <h2 className="text-lg font-black uppercase tracking-wider">{title}</h2>
      </div>
      <p className={cx("text-sm", toneStyle.body)}>{description}</p>
      {action}
    </GlassCard>
  );
}

export function ProjectMonitoringAlert({
  icon: Icon,
  title,
  description,
  tone = "amber",
  className,
}: ProjectMonitoringAlertProps) {
  const toneStyle = toneStyles[tone];

  return (
    <GlassCard className={cx("p-4", toneStyle.card, className)}>
      <div className={cx("flex items-start gap-3", toneStyle.header)}>
        <Icon className="mt-0.5 h-5 w-5" />
        <div>
          <p className="text-sm font-semibold">{title}</p>
          <p className={cx("mt-1 text-xs", toneStyle.body)}>{description}</p>
        </div>
      </div>
    </GlassCard>
  );
}

export function ProjectMonitoringEmptyState({
  icon,
  title,
  description,
  action,
  className,
}: ProjectMonitoringEmptyStateProps) {
  return (
    <GlassCard className={cx("space-y-5 p-8", className)}>
      <EmptyState icon={icon} title={title} description={description} action={action} />
    </GlassCard>
  );
}

export function ProjectMonitoringMetricCard({
  label,
  value,
  meta,
  className,
}: ProjectMonitoringMetricCardProps) {
  return (
    <GlassCard className={cx("space-y-1 p-5", className)}>
      <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">{label}</p>
      <div className="mt-2">{value}</div>
      {meta ? <div className="mt-2 text-xs text-(--t-2)">{meta}</div> : null}
    </GlassCard>
  );
}

export function ProjectMonitoringWidgetCard({
  icon: Icon,
  title,
  description,
  headerAside,
  children,
  className,
  iconShellClassName,
  iconClassName,
}: ProjectMonitoringWidgetCardProps) {
  return (
    <div className={cx("rounded border-0 bg-(--line-2) p-6", className)}>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className={cx(
              "flex h-10 w-10 items-center justify-center rounded-xl border-0 bg-primary/10",
              iconShellClassName
            )}
          >
            <Icon className={cx("h-5 w-5 text-primary", iconClassName)} />
          </div>
          <div>
            <h3 className="text-sm font-bold tracking-wide text-(--foreground)">{title}</h3>
            {description ? (
              <p className="mt-0.5 text-[11px] text-(--text-soft)">{description}</p>
            ) : null}
          </div>
        </div>
        {headerAside}
      </div>

      {children}
    </div>
  );
}

export function ProjectMonitoringWidgetInlineError({
  message,
  tone = "amber",
  className,
}: ProjectMonitoringWidgetInlineErrorProps) {
  return (
    <div
      className={cx(
        "mb-4 flex items-center gap-2 rounded-lg border p-3 text-xs",
        tone === "rose"
          ? "border-rose-500/20 bg-rose-500/10 text-rose-300"
          : "border-amber-500/20 bg-amber-500/10 text-amber-400",
        className
      )}
    >
      <AlertCircle className="h-4 w-4" />
      <span>{message}</span>
    </div>
  );
}

export function ProjectMonitoringWidgetEmptyState({
  icon: Icon,
  title,
  description,
  className,
}: ProjectMonitoringWidgetEmptyStateProps) {
  return (
    <div className={cx("flex flex-col items-center justify-center py-12 text-center", className)}>
      <Icon className="mb-3 h-9 w-9 text-(--t-3)" />
      <p className="text-sm font-medium text-(--t-2)">{title}</p>
      <p className="mt-1 max-w-sm text-xs text-(--t-3)">{description}</p>
    </div>
  );
}
