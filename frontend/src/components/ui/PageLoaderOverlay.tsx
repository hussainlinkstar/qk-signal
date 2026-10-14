"use client";

import React, { type ReactNode } from "react";

import { cx } from "@/components/ui/utils";
import { SignalLoader } from "@/components/ui/SignalLoader";

type PageLoaderOverlayProps = {
  loading: boolean;
  label: string;
  detail?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  overlayClassName?: string;
};

/**
 * Dims the wrapped content and floats the signal-MVP loader over it while
 * `loading`. Replaces the legacy dark "Intelligence Engine" synapse overlay
 * with the light, flat gradient-ring loader that matches signal.css.
 */
export default function PageLoaderOverlay({
  loading,
  label,
  detail,
  children,
  className,
  contentClassName,
  overlayClassName,
}: PageLoaderOverlayProps) {
  return (
    <div className={cx("relative", className)} aria-busy={loading || undefined}>
      <div
        className={cx(
          "transition-[filter,opacity] duration-300",
          loading && "pointer-events-none select-none blur-[5px] opacity-60",
          contentClassName
        )}
      >
        {children}
      </div>

      {loading ? (
        <div
          className={cx(
            "absolute inset-0 z-40 flex items-center justify-center overflow-hidden rounded-[inherit]",
            "bg-[color-mix(in_srgb,var(--paper)_72%,transparent)] backdrop-blur-[3px]",
            overlayClassName
          )}
        >
          <SignalLoader inline label={label} detail={detail} />
        </div>
      ) : null}
    </div>
  );
}
