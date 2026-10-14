"use client";

import React, { type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/components/ui/utils";

export type SignalAlertTone = "info" | "warning" | "danger" | "success";

type Tone = SignalAlertTone;

type Props = {
  title: ReactNode;
  children: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  actions?: ReactNode;
  onDismiss?: () => void;
  dismissLabel?: string;
  className?: string;
  /**
   * Defaults from the tone: a failure announces itself (`alert`), a
   * confirmation does not interrupt (`status`). Pass it explicitly only to
   * override that, never to downgrade a failure.
   */
  role?: "alert" | "status" | "note";
  /**
   * The machine-readable handle for one failure - a status plus backend error
   * code, or `HTTP 503`. Rendered as its own `Reference:` line so a customer
   * can quote it in a report. First shipped inside PlanChangeModal
   * (SIGV2-1172) and generalised here (SIGV2-1171) so every surface can carry
   * it rather than each re-inventing the line.
   */
  reference?: string | null;
  referenceLabel?: string;
};

/* SIGV2-1222: the tinted fill and the 1px edge are no longer utilities here.
   Both are driven by the `[data-signal-alert="<tone>"]` rules in globals.css,
   because the edge is an animated gradient painted into the border box and a
   `border-color` utility would fight it. The tokens and the per-tone values
   are unchanged; only where they are declared moved. */
const iconColors: Record<Tone, string> = {
  info: "text-(--blue)",
  warning: "text-(--warn)",
  danger: "text-(--bad)",
  success: "text-(--good)",
};
/* The approved `.alert` glyphs (mockup: Signal Components.html, #sec-alerts):
   info a circled "i", success a circled check, warn a triangle, danger a
   circled cross. Four distinct shapes, so a failure is never told apart from a
   confirmation by colour alone. */
const icons = { info: Info, warning: AlertTriangle, danger: XCircle, success: CheckCircle2 };

const defaultRoles: Record<Tone, "alert" | "status"> = {
  info: "status",
  success: "status",
  warning: "alert",
  danger: "alert",
};

/* The close control's accessible name. It lives in en.json and ar.json so the
   Arabic build names it in Arabic (SIGV2-1222), but this component is rendered
   bare by its own component test and with a mocked `react-i18next` by several
   others, and in both cases `t` hands the key straight back. Falling through to
   the English string there keeps a mocked suite from asserting against
   "alerts.dismiss" and, more importantly, keeps the control from ever shipping
   a raw key as its label. */
const DISMISS_FALLBACK = "Dismiss notification";
const DISMISS_KEY = "alerts.dismiss";

export const SIGNAL_ALERT_ACTION =
  "inline-flex min-h-[38px] items-center justify-center gap-2 rounded-(--r-md) border border-(--line) bg-(--panel) px-[15px] py-2 text-[13px] font-semibold leading-[1.5] text-(--t-1) transition-colors duration-150 hover:border-(--line-btn-hover) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand) disabled:cursor-not-allowed disabled:opacity-45";

export default function SignalAlert({
  title,
  children,
  tone = "info",
  icon,
  actions,
  onDismiss,
  dismissLabel,
  className,
  role,
  reference,
  referenceLabel = "Reference",
}: Props) {
  const { t } = useTranslation();
  const Icon = icons[tone];
  const translatedDismiss = t(DISMISS_KEY, { defaultValue: DISMISS_FALLBACK });
  const resolvedDismissLabel =
    dismissLabel ?? (translatedDismiss === DISMISS_KEY ? DISMISS_FALLBACK : translatedDismiss);
  const trimmedReference = typeof reference === "string" ? reference.trim() : "";
  return (
    <section
      role={role ?? defaultRoles[tone]}
      data-slot="alert"
      data-signal-alert={tone}
      className={cn(
        "relative flex items-start gap-[11px] rounded-(--r-md) px-[15px] py-[13px] font-(family-name:--body-font) text-[13px] leading-[1.5] text-(--t-2)",
        onDismiss && "pe-12",
        className
      )}
    >
      <span
        data-slot="alert-icon"
        aria-hidden="true"
        className={cn(
          "flex h-8 w-8 flex-none items-center justify-center rounded-full bg-(--al-icon-fill) shadow-sm [&_svg]:h-[17px] [&_svg]:w-[17px]",
          iconColors[tone]
        )}
      >
        {icon ?? <Icon strokeWidth={2} />}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="min-w-0 flex-1">
          <div data-slot="alert-title" className="mb-0.5 text-[13.5px] font-bold text-(--t-1)">
            {title}
          </div>
          <div data-slot="alert-description" className="break-words">
            {children}
          </div>
          {trimmedReference ? (
            <p className="m-0 mt-1 font-(family-name:--mono) text-[11.5px] text-(--t-3)">
              {referenceLabel}: {trimmedReference}
            </p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex flex-none flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
      {onDismiss ? (
        <button
          type="button"
          aria-label={resolvedDismissLabel}
          onClick={onDismiss}
          className="absolute end-2 top-2 flex h-7 w-7 items-center justify-center rounded-[6px] text-(--t-3) transition-colors duration-150 hover:bg-(--line-2) hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand)"
        >
          <X className="h-[13px] w-[13px]" aria-hidden="true" />
        </button>
      ) : null}
    </section>
  );
}
