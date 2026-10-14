import React, { type ReactNode } from "react";
import { AlertCircle, Info, type LucideIcon } from "lucide-react";

import PageLoaderOverlay from "@/components/ui/PageLoaderOverlay";
import { GlassCard } from "@/components/ui/GlassComponents";
import { Skeleton } from "@/components/ui/Loading";
import Tooltip from "@/components/ui/Tooltip";
import {
  CARD_CONTAINER_PRESETS,
  CARD_LABEL_CLASS,
  CARD_RADIUS_OUTER_CLASS,
  CARD_SUBSECTION_SURFACE_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import { getScoreColor } from "@/lib/scoreColors";
import { formatDateTime } from "@/lib/dateFormat";
import { cx } from "@/components/ui/utils";

export type ProjectFeatureTone = "primary" | "accent" | "indigo" | "rose" | "amber" | "slate";

type ProjectFeatureHeaderProps = {
  icon: LucideIcon;
  title: string;
  accent: string;
  tone?: ProjectFeatureTone;
  targetType?: string;
  targetLabel?: string;
  description?: ReactNode;
  className?: string;
  descriptionClassName?: string;
};

type ProjectMetricCardProps = {
  label: string;
  value: ReactNode;
  icon: ReactNode;
  tone?: ProjectFeatureTone;
  info?: string;
  score?: number | null;
  className?: string;
  valueClassName?: string;
};

type ProjectFeatureEmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  action?: ReactNode;
  tone?: ProjectFeatureTone;
  className?: string;
};

type ProjectFeatureErrorStateProps = {
  message: ReactNode;
  title?: string;
  action?: ReactNode;
  className?: string;
};

type ProjectFeatureBannerProps = {
  title: string;
  message: ReactNode;
  action?: ReactNode;
  tone?: ProjectFeatureTone;
  className?: string;
};

type ProjectFeatureLoadingViewProps = {
  label: string;
  icon: LucideIcon;
  title: string;
  accent: string;
  tone?: ProjectFeatureTone;
  description?: ReactNode;
  metrics?: number;
  panels?: number;
};

const toneStyles: Record<
  ProjectFeatureTone,
  {
    accentText: string;
    line: string;
    iconBorder: string;
    iconBg: string;
    iconText: string;
    shadow: string;
    panelBorder: string;
    panelBg: string;
    badgeText: string;
  }
> = {
  primary: {
    accentText: "text-primary",
    line: "from-primary/20",
    iconBorder: "border-primary/30",
    iconBg: "bg-primary/10",
    iconText: "text-primary",
    shadow: "shadow-[0_0_15px_rgba(6,182,212,0.1)]",
    panelBorder: "border-primary/20",
    panelBg: "bg-primary/[0.01]",
    badgeText: "text-primary",
  },
  accent: {
    accentText: "text-accent",
    line: "from-accent/20",
    iconBorder: "border-accent/30",
    iconBg: "bg-accent/10",
    iconText: "text-accent",
    shadow: "shadow-[0_0_15px_rgba(34,211,238,0.1)]",
    panelBorder: "border-accent/20",
    panelBg: "bg-accent/[0.01]",
    badgeText: "text-accent",
  },
  indigo: {
    accentText: "text-(--purple)",
    line: "from-indigo-500/20",
    iconBorder: "border-[color-mix(in_srgb,var(--purple)_30%,transparent)]",
    iconBg: "bg-[color-mix(in_srgb,var(--purple)_10%,transparent)]",
    iconText: "text-(--purple)",
    shadow: "shadow-[0_0_15px_rgba(99,102,241,0.1)]",
    panelBorder: "border-[color-mix(in_srgb,var(--purple)_20%,transparent)]",
    panelBg: "",
    badgeText: "text-(--purple)",
  },
  rose: {
    accentText: "text-rose-400",
    line: "from-rose-500/20",
    iconBorder: "border-rose-500/30",
    iconBg: "bg-rose-500/10",
    iconText: "text-rose-400",
    shadow: "shadow-[0_0_15px_rgba(244,63,94,0.12)]",
    panelBorder: "border-rose-500/20",
    panelBg: "",
    badgeText: "text-rose-400",
  },
  amber: {
    accentText: "text-amber-300",
    line: "from-amber-300/20",
    iconBorder: "border-amber-300/30",
    iconBg: "bg-amber-300/10",
    iconText: "text-amber-300",
    shadow: "shadow-[0_0_15px_rgba(252,211,77,0.1)]",
    panelBorder: "border-amber-300/20",
    panelBg: "",
    badgeText: "text-amber-300",
  },
  slate: {
    accentText: "text-(--t-2)",
    line: "from-slate-500/20",
    iconBorder: "border-(--line)",
    iconBg: "bg-(--line-2)",
    iconText: "text-(--t-2)",
    shadow: "shadow-[0_0_15px_rgba(148,163,184,0.08)]",
    panelBorder: "border-(--line)",
    panelBg: "",
    badgeText: "text-(--t-2)",
  },
};

export function ProjectFeatureHeader({
  icon: Icon,
  title,
  accent,
  tone = "primary",
  targetType,
  targetLabel,
  description,
  className,
  descriptionClassName,
}: ProjectFeatureHeaderProps) {
  const toneStyle = toneStyles[tone];

  return (
    <div className={cx("space-y-2 border-b border-(--line) pb-5", className)}>
      <div className="flex items-center gap-2">
        <Icon className={cx("h-4 w-4", toneStyle.accentText)} />
        <span
          className={cx(
            "font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em]",
            toneStyle.accentText
          )}
        >
          {accent}
        </span>
      </div>
      <h1 className="font-(family-name:--disp) text-[26px] font-black tracking-[-0.02em] text-(--t-1)">
        {title}
      </h1>

      {description ? (
        <div className={cx("text-[13.5px] leading-relaxed text-(--t-2)", descriptionClassName)}>
          {description}
        </div>
      ) : null}

      {targetType || targetLabel ? (
        <p className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.08em] text-(--t-3)">
          Target ({targetType ?? "website"}):{" "}
          <span className="text-(--t-2)">{targetLabel || "N/A"}</span>
        </p>
      ) : null}
    </div>
  );
}

export function ProjectMetricCard({
  label,
  value,
  icon,
  tone = "primary",
  info,
  score = null,
  className,
  valueClassName,
}: ProjectMetricCardProps) {
  const toneStyle = toneStyles[tone];
  const hasScore = typeof score === "number" && Number.isFinite(score);
  const scoreColor = hasScore ? getScoreColor(score) : null;

  return (
    <GlassCard
      className={cx(
        CARD_CONTAINER_PRESETS.compact,
        "relative overflow-visible transition-all",
        tone === "indigo"
          ? "hover:border-[color-mix(in_srgb,var(--purple)_20%,transparent)]"
          : "hover:border-primary/20",
        className
      )}
    >
      {info ? (
        <div className="absolute right-4 top-4 z-20">
          <Tooltip content={info}>
            <div className="flex h-5 w-5 cursor-help items-center justify-center rounded-full border border-[color-mix(in_srgb,var(--line)_50%,transparent)] bg-[color-mix(in_srgb,var(--line-2)_50%,transparent)] text-(--t-2) transition-colors hover:bg-slate-700 hover:text-(--t-1)">
              <Info className="h-3 w-3" />
            </div>
          </Tooltip>
        </div>
      ) : null}

      <div className="mb-4 mt-2 flex items-center justify-between">
        <p className={CARD_LABEL_CLASS}>{label}</p>
        <div
          className={cx(
            "flex h-8 w-8 items-center justify-center rounded-xl border",
            scoreColor ? scoreColor.bg + "/10" : toneStyle.iconBg,
            scoreColor ? scoreColor.text : toneStyle.iconText
          )}
          style={scoreColor ? { borderColor: `${scoreColor.hex}40` } : undefined}
        >
          {icon}
        </div>
      </div>

      <p
        className={cx(TYPO.metric, scoreColor?.text ?? toneStyle.badgeText, valueClassName)}
        style={scoreColor ? { textShadow: `0 0 10px ${scoreColor.hex}40` } : undefined}
      >
        {value}
      </p>
    </GlassCard>
  );
}

export function ProjectFeatureErrorState({
  message,
  title = "Data Sync Error",
  action,
  className,
}: ProjectFeatureErrorStateProps) {
  return (
    <GlassCard className={cx(CARD_CONTAINER_PRESETS.primary, "border-rose-500/20 ", className)}>
      <div className="mb-2 flex items-center gap-3 text-rose-400">
        <AlertCircle size={18} />
        <p className={CARD_LABEL_CLASS}>{title}</p>
      </div>
      <p className="text-sm text-(--text-soft)">{message}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </GlassCard>
  );
}

export function ProjectFeatureBanner({
  title,
  message,
  action,
  tone = "amber",
  className,
}: ProjectFeatureBannerProps) {
  const toneStyle = toneStyles[tone];

  return (
    <GlassCard
      className={cx(
        CARD_RADIUS_OUTER_CLASS,
        "flex flex-col gap-4 border px-6 py-[22px] md:flex-row md:items-center md:justify-between",
        toneStyle.panelBorder,
        toneStyle.panelBg,
        className
      )}
    >
      <div className="space-y-2">
        <p className={cx(CARD_LABEL_CLASS, toneStyle.badgeText)}>{title}</p>
        <div className="text-sm leading-relaxed text-(--text-soft)">{message}</div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </GlassCard>
  );
}

export function ProjectFeatureEmptyState({
  icon: Icon,
  title,
  description,
  action,
  tone = "primary",
  className,
}: ProjectFeatureEmptyStateProps) {
  const toneStyle = toneStyles[tone];

  return (
    <GlassCard
      className={cx(
        CARD_CONTAINER_PRESETS.primary,
        "mx-auto max-w-2xl text-center",
        toneStyle.panelBorder,
        toneStyle.panelBg,
        className
      )}
    >
      <div
        className={cx(
          "mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded border shadow-[0_0_30px_rgba(15,23,42,0.25)]",
          toneStyle.iconBorder,
          toneStyle.iconBg,
          toneStyle.iconText
        )}
      >
        <Icon size={32} />
      </div>
      <h2 className={cx(TYPO.pageTitle, "mb-4")}>{title}</h2>
      <div className="mb-8 text-sm leading-relaxed text-(--text-soft)">{description}</div>
      {action}
    </GlassCard>
  );
}

export function ProjectFeatureMetaRow({
  auditType,
  targetType,
  date,
}: {
  auditType?: string | null;
  targetType?: string | null;
  date?: string | null;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-(--line) pt-6">
      <p className={CARD_LABEL_CLASS}>
        Audit Type: <span className="text-(--text-soft)">{auditType || "N/A"}</span>
      </p>
      {targetType ? (
        <p className={CARD_LABEL_CLASS}>
          Target: <span className="text-(--text-soft)">{targetType}</span>
        </p>
      ) : null}
      <p className={CARD_LABEL_CLASS}>
        Date: <span className="text-(--text-soft)">{date ? formatDateTime(date) : "N/A"}</span>
      </p>
    </div>
  );
}

export function ProjectFeatureLoadingView({
  label,
  icon,
  title,
  accent,
  tone = "primary",
  description,
  metrics = 4,
  panels = 2,
}: ProjectFeatureLoadingViewProps) {
  const toneStyle = toneStyles[tone];

  return (
    <PageLoaderOverlay loading label={label}>
      <section className="space-y-10">
        <ProjectFeatureHeader
          icon={icon}
          title={title}
          accent={accent}
          tone={tone}
          targetType="project"
          targetLabel="Preparing latest audit telemetry"
          description={description}
        />

        <div className={cx("grid gap-6", metrics >= 4 ? "md:grid-cols-4" : "md:grid-cols-3")}>
          {Array.from({ length: metrics }).map((_, index) => (
            <GlassCard key={`metric-skeleton-${index}`} className={CARD_CONTAINER_PRESETS.compact}>
              <div className="mb-4 mt-2 flex items-center justify-between">
                <Skeleton className="h-3 w-28" />
                <Skeleton variant="circle" className="h-8 w-8" />
              </div>
              <Skeleton className="h-10 w-20" />
            </GlassCard>
          ))}
        </div>

        <div className={cx("grid gap-8", panels > 1 ? "lg:grid-cols-2" : undefined)}>
          {Array.from({ length: panels }).map((_, index) => (
            <GlassCard
              key={`panel-skeleton-${index}`}
              className={cx(
                CARD_CONTAINER_PRESETS.primary,
                toneStyle.panelBorder,
                toneStyle.panelBg
              )}
            >
              <div className="mb-8 flex items-center gap-3">
                <Skeleton variant="circle" className="h-8 w-8" />
                <Skeleton className="h-3 w-40" />
              </div>
              <div className="space-y-4">
                {Array.from({ length: 3 }).map((__, rowIndex) => (
                  <div
                    key={`row-skeleton-${index}-${rowIndex}`}
                    className={CARD_SUBSECTION_SURFACE_CLASS}
                  >
                    <Skeleton className="h-3 w-28" />
                    <Skeleton className="mt-3 h-4 w-full" />
                    <Skeleton className="mt-2 h-4 w-5/6" />
                  </div>
                ))}
              </div>
            </GlassCard>
          ))}
        </div>
      </section>
    </PageLoaderOverlay>
  );
}
