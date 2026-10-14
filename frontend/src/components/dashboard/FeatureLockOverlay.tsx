import React from "react";
import Link from "next/link";
import { ArrowRight, Lock } from "lucide-react";

import { buttonClasses } from "@/components/ui/Button";
import { CARD_LABEL_CLASS } from "@/components/ui/cardStyleTokens";
import { LABEL_CLASS } from "@/components/ui/typographyTokens";
import { cx } from "@/components/ui/utils";

export default function FeatureLockOverlay({
  title,
  description,
  ctaLabel = "Upgrade plan",
  href = "/dashboard/billing",
  eyebrow = "Plan locked",
  className = "rounded-xl",
}: {
  title: string;
  description: string;
  ctaLabel?: string;
  href?: string;
  eyebrow?: string;
  className?: string;
}) {
  return (
    <div
      className={cx(
        // Approved `.lockgate`: a light --gate-veil wash that frosts the locked
        // content itself (blur 6px, the `.lockcontent` radius), so the panel
        // reads on any caller whether or not it blurs its own children. Dark
        // surfaces fall back to --overlay-backdrop via the token.
        "absolute inset-0 z-20 flex items-center justify-center bg-(--gate-veil) p-4 backdrop-blur-[6px]",
        className
      )}
    >
      {/* `.lockcard`: 380px, 16px radius, 22/24 padding. surface-card-strong
          supplies the themed panel colour, border and shadow. */}
      <div className="w-full max-w-[380px] surface-card-strong px-6 py-[22px] text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-md border border-accent/30 bg-accent/10 text-accent">
          <Lock className="h-5 w-5" />
        </div>
        <p className={cx("mt-4 text-accent", CARD_LABEL_CLASS)}>{eyebrow}</p>
        <h2
          className={cx(
            "mt-3 font-(family-name:--disp) text-[14.5px] font-bold tracking-[-0.01em] text-(--foreground)"
          )}
        >
          {title}
        </h2>
        <p className={cx("mt-3 leading-6", LABEL_CLASS)}>{description}</p>
        <Link className={cx(buttonClasses({ variant: "primary", size: "md" }), "mt-5")} href={href}>
          {ctaLabel}
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}
