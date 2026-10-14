"use client";

import React from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Circle, Sparkles } from "lucide-react";

import Button, { buttonClasses } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { cx } from "@/components/ui/utils";

export type GettingStartedItem = {
  id: string;
  title: string;
  description: string;
  completed: boolean;
  optional?: boolean;
  href?: string;
  onClick?: () => void;
};

type GettingStartedChecklistProps = {
  items: GettingStartedItem[];
  onDismiss: () => void;
};

export default function GettingStartedChecklist({
  items,
  onDismiss,
}: GettingStartedChecklistProps) {
  const requiredItems = items.filter((item) => !item.optional);
  const nextRequiredItem = requiredItems.find((item) => !item.completed);
  const requiredCompleted = requiredItems.filter((item) => item.completed).length;
  const progressPercentage = requiredItems.length
    ? Math.round((requiredCompleted / requiredItems.length) * 100)
    : 0;
  const progressLabel = `${requiredCompleted} of ${requiredItems.length} required steps completed`;

  return (
    <Card variant="surface" className="relative overflow-hidden border-(--border)">
      <div className="space-y-5 p-6 md:p-7">
        {/* Header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-(--foreground)">Getting Started</h3>
            <p className="mt-1 text-sm text-(--muted-foreground)">
              Complete these steps to unlock the full platform.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs font-medium tabular-nums text-(--muted-foreground)">
              {progressPercentage}%
            </span>
            <Button type="button" variant="ghost" size="sm" onClick={onDismiss}>
              Dismiss
            </Button>
          </div>
        </div>

        {/* Progress bar */}
        <div>
          <div
            role="progressbar"
            aria-label={progressLabel}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progressPercentage}
            className="h-1.5 w-full overflow-hidden rounded-full "
          >
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-300 w-(--bw)"
              style={{ "--bw": `${progressPercentage}%` } as React.CSSProperties}
            />
          </div>
          <p className="mt-2 text-xs text-(--muted-foreground)">{progressLabel}</p>
        </div>

        {nextRequiredItem ? (
          <ul className="space-y-2">
            <li>
              <StepRow item={nextRequiredItem} isNext />
            </li>
          </ul>
        ) : null}
      </div>
    </Card>
  );
}

function StepRow({
  item,
  isNext,
  isOptional,
}: {
  item: GettingStartedItem;
  isNext?: boolean;
  isOptional?: boolean;
}) {
  const isActionable = !item.completed && (item.href || item.onClick);

  const content = (
    <div
      className={cx(
        "group/step flex w-full items-center gap-3 rounded border px-4 py-3 text-left transition-colors",
        item.completed
          ? "border-emerald-500/15 "
          : isNext
            ? "border-primary/25 bg-primary/[0.04] hover:border-primary/40"
            : "border-(--border) hover:border-(--border-hover)"
      )}
    >
      {/* Icon */}
      <div className="shrink-0">
        {item.completed ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
        ) : isOptional ? (
          <Sparkles className="h-5 w-5 text-(--muted-foreground)" />
        ) : (
          <Circle
            className={cx("h-5 w-5", isNext ? "text-primary" : "text-(--muted-foreground)")}
          />
        )}
      </div>

      {/* Text */}
      <div className="min-w-0 flex-1">
        <p
          className={cx(
            "text-sm font-medium",
            item.completed ? "text-emerald-200" : "text-(--foreground)"
          )}
        >
          {item.title}
        </p>
        {!item.completed ? (
          <p className="mt-0.5 text-xs text-(--muted-foreground)">{item.description}</p>
        ) : null}
      </div>

      {/* Action hint */}
      {isActionable && isNext ? (
        <Link
          href={item.href ?? "#"}
          onClick={
            item.onClick
              ? (e) => {
                  e.preventDefault();
                  item.onClick?.();
                }
              : undefined
          }
          className={buttonClasses({ variant: "primary", size: "sm" })}
        >
          Continue
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      ) : isActionable ? (
        <div className="hidden shrink-0 items-center gap-1 text-xs font-medium text-(--muted-foreground) sm:flex">
          <span>Open</span>
          <ArrowRight className="h-3 w-3 transition-transform group-hover/step:translate-x-0.5" />
        </div>
      ) : null}
    </div>
  );

  if (isActionable && !isNext) {
    if (item.href) {
      return (
        <Link href={item.href} className="block">
          {content}
        </Link>
      );
    }
    return (
      <button type="button" onClick={item.onClick} className="block w-full">
        {content}
      </button>
    );
  }

  return content;
}
