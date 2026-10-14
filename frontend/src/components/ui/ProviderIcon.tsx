import { asset } from "@/lib/basePath";
import React from "react";
import Image from "next/image";

import { resolveAuditProviderConfig } from "@/constants/auditModelMap";
import { cx } from "@/components/ui/utils";

export interface ProviderIconProps {
  providerId: string;
  className?: string;
  width?: number;
  height?: number;
}

export default function ProviderIcon({
  providerId,
  className = "h-5 w-5",
  width = 20,
  height = 20,
}: ProviderIconProps) {
  const config = resolveAuditProviderConfig(providerId);

  if (!config?.icon || typeof config.icon !== "string") {
    return null;
  }

  return (
    <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/95 p-1.5 shadow-[0_8px_20px_rgba(0,0,0,0.18)]">
      <Image
        alt={`${config.label} logo`}
        className={cx("object-contain", className)}
        height={height}
        src={asset(config.icon)}
        width={width}
      />
    </span>
  );
}
