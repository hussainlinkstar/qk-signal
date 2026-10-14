"use client";

import React, { type ReactNode } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Info, ShieldCheck } from "lucide-react";

import Button, { buttonClasses, type ButtonVariant } from "@/components/ui/Button";
import SignalAlert, { type SignalAlertTone } from "@/components/signal/SignalAlert";
import { cx } from "@/components/ui/utils";

export type AuthStatusChip = {
  variant: "success" | "warning" | "progress" | "trust";
  label: string;
};

export type AuthStateHeaderProps = {
  title: string;
  subtitle?: string;
  chip?: AuthStatusChip;
  className?: string;
};

export const AUTH_STATES = {
  entering: "entering credentials",
  verifying: "verifying identity",
  handoff: "waiting for provider",
  completing: "completing secure session",
  recovering: "recovering account access",
  expired: "session expired",
  success: "action completed",
  failed: "action blocked",
} as const;

type AuthInlineNoticeProps = {
  variant: "warning" | "error" | "success" | "progress";
  title: string;
  description: string;
  className?: string;
};

type AuthRecoveryAction = {
  label: string;
  href?: string;
  onClick?: () => void;
  variant?: ButtonVariant;
};

type AuthRecoveryCardProps = {
  title: string;
  description: string;
  primaryAction: AuthRecoveryAction;
  secondaryAction?: AuthRecoveryAction;
  className?: string;
};

const statusChipClassByVariant: Record<AuthStatusChip["variant"], string> = {
  success: "border-transparent bg-(--good-s) text-(--good)",
  warning: "border-transparent bg-(--warn-s) text-(--warn)",
  progress: "border-transparent bg-(--blue-s) text-(--blue)",
  trust: "border-transparent bg-(--purple-s) text-(--purple)",
};

const statusChipIconByVariant: Record<AuthStatusChip["variant"], ReactNode> = {
  success: <CheckCircle2 className="h-3.5 w-3.5" />,
  warning: <AlertTriangle className="h-3.5 w-3.5" />,
  progress: <Info className="h-3.5 w-3.5" />,
  trust: <ShieldCheck className="h-3.5 w-3.5" />,
};

const noticeToneByVariant: Record<AuthInlineNoticeProps["variant"], SignalAlertTone> = {
  warning: "warning",
  error: "danger",
  success: "success",
  progress: "info",
};

const resolveActionVariant = (variant: ButtonVariant | undefined): ButtonVariant =>
  !variant || variant === "primary" || variant === "inverse" ? "auth" : variant;

const renderAction = (action: AuthRecoveryAction, key: string) => {
  if (action.href) {
    return (
      <Link
        key={key}
        className={buttonClasses({ variant: resolveActionVariant(action.variant), size: "md" })}
        href={action.href}
      >
        {action.label}
      </Link>
    );
  }

  return (
    <Button
      key={key}
      type="button"
      variant={resolveActionVariant(action.variant)}
      size="md"
      onClick={action.onClick}
    >
      {action.label}
    </Button>
  );
};

export function AuthStateHeader({ title, subtitle, chip, className }: AuthStateHeaderProps) {
  return (
    <header className={cx("space-y-3", className)}>
      {chip ? (
        <div
          className={cx(
            "inline-flex items-center gap-1.5 rounded-[6px] border px-2 py-1 text-[11.5px] font-medium tracking-normal",
            statusChipClassByVariant[chip.variant]
          )}
        >
          {statusChipIconByVariant[chip.variant]}
          {chip.label}
        </div>
      ) : null}
      <h2 className="font-(family-name:--disp) text-[17px] font-bold leading-[1.35] tracking-[-0.01em] text-(--t-1)">
        {title}
      </h2>
      {subtitle ? <p className="text-[13px] leading-[1.5] text-(--t-2)">{subtitle}</p> : null}
    </header>
  );
}

export function AuthInlineNotice({
  variant,
  title,
  description,
  className,
}: AuthInlineNoticeProps) {
  return (
    <SignalAlert tone={noticeToneByVariant[variant]} title={title} className={className}>
      {description}
    </SignalAlert>
  );
}

export function AuthRecoveryCard({
  title,
  description,
  primaryAction,
  secondaryAction,
  className,
}: AuthRecoveryCardProps) {
  return (
    <SignalAlert
      tone="danger"
      title={<h2>{title}</h2>}
      className={className}
      actions={
        <>
          {renderAction(primaryAction, "primary")}
          {secondaryAction ? renderAction(secondaryAction, "secondary") : null}
        </>
      }
    >
      {description}
    </SignalAlert>
  );
}
