"use client";

import React from "react";
import { Info } from "lucide-react";

import { LABEL_CLASS } from "@/components/ui/typographyTokens";
import { cx } from "@/components/ui/utils";

type AiDisclaimerProps = {
  text?: string;
  className?: string;
};

const DEFAULT_TEXT =
  "Grounded strategic insights are derived from audits and project evidence. Verify roadmap items before deployment.";

export default function AiDisclaimer({ text = DEFAULT_TEXT, className }: AiDisclaimerProps) {
  return (
    <div
      role="note"
      aria-label="AI disclaimer"
      className={cx("flex items-start gap-2 rounded-xl border   px-3 py-2", className)}
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
      <p
        className={cx(
          LABEL_CLASS,
          "text-xs font-normal normal-case tracking-normal text-slate-400"
        )}
      >
        {text}
      </p>
    </div>
  );
}
