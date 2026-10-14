import Image from "next/image";
import React from "react";

import { cx } from "@/components/ui/utils";
import { asset } from "@/lib/basePath";

/**
 * The single approved product lockup: the Qiko wordmark (`qiko-logo.png`)
 * beside the Signal word. signal.css `.brand`: logo height 21px width auto,
 * gap 9px, word = --disp 16px/500 ls -.01em --t-3.
 *
 * `size="auth"` keeps the larger lockup Razvan approved on the auth pages
 * (32px logo, 22px word, 6px gap) while sharing the same asset and markup.
 * Render inside the surface's own link/button so the lockup stays one
 * labelled target.
 */
export default function SignalBrandLockup({
  size = "default",
  word = "Signal",
  className,
}: {
  size?: "default" | "auth";
  word?: string;
  className?: string;
}) {
  const auth = size === "auth";
  return (
    <span className={cx("flex items-center", auth ? "gap-[6px]" : "gap-[9px]", className)}>
      <Image
        alt="Qiko"
        src={asset("/qiko-logo.png")}
        width={auth ? 80 : 237}
        height={auth ? 32 : 95}
        unoptimized
        priority
        className={cx("block w-auto flex-none", auth ? "h-8" : "h-[21px]")}
      />
      <span
        className={cx(
          "font-(family-name:--disp) font-medium leading-none tracking-[-0.01em]",
          auth ? "text-[22px] text-(--t-2)" : "text-[16px] text-(--t-3)"
        )}
      >
        {word}
      </span>
    </span>
  );
}
