"use client";

import { useState, type CSSProperties } from "react";

import { cx } from "@/components/ui/utils";

function hostnameFromDomain(domain: string | null | undefined): string | null {
  if (!domain) return null;
  try {
    const url = domain.includes("://") ? new URL(domain) : new URL(`https://${domain}`);
    return url.hostname || null;
  } catch {
    return null;
  }
}

type ProjectFaviconProps = {
  domain?: string | null;
  letter: string;
  className?: string;
  style?: CSSProperties;
};

/**
 * Site favicon when available; letter tile fallback otherwise
 * (Signal UI/UX Fixes: "Real favicons, not letter avatars").
 */
export default function ProjectFavicon({ domain, letter, className, style }: ProjectFaviconProps) {
  const host = hostnameFromDomain(domain);
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(host) && !failed;

  return (
    <div
      className={cx(
        "flex h-10 w-10 flex-none items-center justify-center overflow-hidden rounded-[12px] font-(family-name:--disp) text-[15px] font-bold",
        className
      )}
      style={showImage ? undefined : style}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- third-party favicon URL
        <img
          src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host as string)}&sz=64`}
          alt=""
          width={28}
          height={28}
          className="h-7 w-7"
          onError={() => setFailed(true)}
        />
      ) : (
        letter
      )}
    </div>
  );
}
