import React from "react";

import { cx } from "@/components/ui/utils";

export type SignalMetricTone = "default" | "good" | "warn" | "bad";

export type SignalMetricItem = {
  label: string;
  value: React.ReactNode;
  /** Optional secondary line under the value. */
  hint?: React.ReactNode;
  tone?: SignalMetricTone;
  /** `text` for long values (dates, URLs); default is the large metric figure. */
  valueSize?: "metric" | "text";
};

type SignalMetricStripProps = {
  items: SignalMetricItem[];
  className?: string;
  /**
   * When true, values sit above labels (default). Set false for label-first
   * stacks that match denser admin telemetry.
   */
  valueFirst?: boolean;
};

const toneCls: Record<SignalMetricTone, string> = {
  default: "text-(--t-1)",
  good: "text-(--good)",
  warn: "text-(--warn)",
  bad: "text-(--bad)",
};

/**
 * Shared metric strip — replaces the old grey `#EEF1F6` inset tiles
 * (uppercase micro-label + big number). One bordered row, purple top rail,
 * hairline cell dividers, sentence-case labels, tabular display values.
 */
export default function SignalMetricStrip({
  items,
  className,
  valueFirst = true,
}: SignalMetricStripProps) {
  const cols =
    items.length <= 1
      ? "grid-cols-1"
      : items.length === 2
        ? "grid-cols-1 sm:grid-cols-2"
        : items.length === 3
          ? "grid-cols-1 sm:grid-cols-3"
          : items.length === 5
            ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5"
            : items.length === 6
              ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
              : "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4";

  return (
    <dl
      className={cx(
        "grid overflow-hidden rounded-[14px] border border-(--line) border-t-2 border-t-(--purple) bg-white",
        cols,
        className
      )}
    >
      {items.map((item, index) => {
        const tone = item.tone ?? "default";
        return (
          <div
            key={`${item.label}-${index}`}
            className={cx(
              "flex min-w-0 flex-col gap-1 px-5 py-4",
              index > 0 && "border-t border-t-(--line-2) sm:border-t-0 sm:border-s sm:border-s-(--line-2)"
            )}
          >
            <dt
              className={cx(
                "m-0 text-[12.5px] font-medium leading-[1.35] text-(--t-2)",
                valueFirst ? "order-2" : "order-1"
              )}
            >
              {item.label}
            </dt>
            <dd
              className={cx(
                "m-0 min-w-0 leading-none",
                item.valueSize === "text"
                  ? "font-(family-name:--body-font) text-[14px] font-semibold tracking-normal break-all"
                  : "font-(family-name:--disp) text-[22px] font-bold tracking-[-0.02em] tabular-nums",
                toneCls[tone],
                valueFirst ? "order-1" : "order-2"
              )}
            >
              {item.value}
            </dd>
            {item.hint ? (
              <p className="order-3 m-0 text-[11.5px] leading-[1.4] text-(--t-3)">{item.hint}</p>
            ) : null}
          </div>
        );
      })}
    </dl>
  );
}
