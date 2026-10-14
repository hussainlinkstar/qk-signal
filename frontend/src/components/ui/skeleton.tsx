import React from "react";
import { cx } from "./utils";
import { RADIUS_CONTROL_CLASS, RADIUS_PILL_CLASS } from "./radiusTokens";

type SkeletonProps = {
  className?: string;
  /** Shape variant: "bar" (default rectangle), "circle" (rounded-full) */
  variant?: "bar" | "circle";
};

function Skeleton({ className, variant = "bar" }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cx(
        "animate-pulse bg-(--surface-subtle)",
        variant === "circle" ? RADIUS_PILL_CLASS : RADIUS_CONTROL_CLASS,
        className
      )}
    />
  );
}

export { Skeleton };
