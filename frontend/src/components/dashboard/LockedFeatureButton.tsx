import Link from "next/link";
import React from "react";
import { Lock } from "lucide-react";

import Button, { type ButtonProps } from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";

type LockedFeatureButtonProps = {
  buttonLabel: string;
  helperText: string;
  href?: string;
  ctaLabel?: string;
  className?: string;
  buttonVariant?: ButtonProps["variant"];
};

export default function LockedFeatureButton({
  buttonLabel,
  helperText,
  href = "/dashboard/billing",
  ctaLabel = "View plans",
  className,
  buttonVariant = "ghost",
}: LockedFeatureButtonProps) {
  return (
    <div className={cx("space-y-3", className)}>
      <Button variant={buttonVariant} disabled aria-disabled="true" className="h-11 w-full">
        <Lock className="h-4 w-4" />
        {buttonLabel}
      </Button>
      <p className="text-xs leading-5 text-amber-200/85">
        {helperText}{" "}
        <Link
          href={href}
          className="font-semibold text-(--t-1) underline decoration-white/30 underline-offset-4"
        >
          {ctaLabel}
        </Link>
        .
      </p>
    </div>
  );
}
