"use client";

import React from "react";
import { CARD_CHIP_CLASS } from "@/components/ui/cardStyleTokens";

export const StatusPill = ({
  tone,
  text,
}: {
  tone: "success" | "warning" | "info";
  text: string;
}) => {
  const toneStyles = {
    success: "bg-emerald-500/10 text-emerald-200 border-emerald-400/40",
    warning: "bg-amber-500/10 text-amber-200 border-amber-400/40",
    info: "bg-sky-500/10 text-sky-200 border-sky-400/40",
  };
  return (
    <span
      className={`inline-flex items-center border px-3 py-1 text-xs font-semibold ${CARD_CHIP_CLASS} ${toneStyles[tone]}`}
    >
      {text}
    </span>
  );
};
