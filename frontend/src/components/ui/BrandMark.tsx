import React from "react";

import BrandLogo from "@/components/ui/BrandLogo";
import { cx } from "@/components/ui/utils";

export type BrandMarkId =
  | "google"
  | "microsoft"
  | "github"
  | "linkedin"
  | "bing"
  | "jira"
  | "slack"
  | "teams";

export const BRAND_MARK_LABELS: Record<BrandMarkId, string> = {
  google: "Google",
  microsoft: "Microsoft",
  github: "GitHub",
  linkedin: "LinkedIn",
  bing: "Bing",
  jira: "Jira",
  slack: "Slack",
  teams: "Microsoft Teams",
};

type BrandMarkProps = {
  brand: BrandMarkId;
  className?: string;
  markClassName?: string;
  variant?: "plain" | "tile";
};

function Svg({
  className,
  viewBox = "0 0 24 24",
  children,
}: {
  className?: string;
  viewBox?: string;
  children: React.ReactNode;
}) {
  return (
    <svg
      aria-hidden="true"
      className={cx("h-5 w-5 shrink-0", className)}
      fill="none"
      viewBox={viewBox}
      xmlns="http://www.w3.org/2000/svg"
    >
      {children}
    </svg>
  );
}

function renderBrandMark(brand: BrandMarkId, className?: string) {
  switch (brand) {
    case "google":
      return (
        <BrandLogo brand="google" decorative className={className} imageClassName={className} />
      );
    case "microsoft":
      return (
        <Svg className={className}>
          <path d="M2 2h9.5v9.5H2z" fill="#F25022" />
          <path d="M12.5 2H22v9.5h-9.5z" fill="#7FBA00" />
          <path d="M2 12.5h9.5V22H2z" fill="#00A4EF" />
          <path d="M12.5 12.5H22V22h-9.5z" fill="#FFB900" />
        </Svg>
      );
    case "github":
      return (
        <Svg className={className} viewBox="0 0 24 24">
          <path
            d="M12 1.5C6.2 1.5 1.5 6.3 1.5 12.2c0 4.7 3 8.7 7.2 10.1.5.1.7-.2.7-.5v-2c-2.9.7-3.5-1.2-3.5-1.2-.5-1.2-1.1-1.6-1.1-1.6-.9-.6.1-.6.1-.6 1 .1 1.6 1.1 1.6 1.1.9 1.5 2.4 1.1 3 .8.1-.7.4-1.1.7-1.4-2.3-.3-4.7-1.2-4.7-5.1 0-1.1.4-2.1 1.1-2.8-.1-.3-.5-1.4.1-2.9 0 0 .9-.3 3 .9a10 10 0 0 1 5.5 0c2.1-1.2 3-.9 3-.9.6 1.5.2 2.6.1 2.9.7.7 1.1 1.7 1.1 2.8 0 3.9-2.4 4.8-4.7 5.1.4.3.7 1 .7 2v3c0 .3.2.6.7.5 4.2-1.4 7.2-5.4 7.2-10.1C22.5 6.3 17.8 1.5 12 1.5Z"
            fill="currentColor"
          />
        </Svg>
      );
    case "linkedin":
      return (
        <Svg className={className} viewBox="0 0 24 24">
          <rect x="2" y="2" width="20" height="20" rx="4" fill="#0A66C2" />
          <path
            d="M7.25 9.25H9.9V17H7.25V9.25Zm1.33-3a1.54 1.54 0 1 1 0 3.08 1.54 1.54 0 0 1 0-3.08ZM11.56 9.25h2.55v1.06h.04c.36-.67 1.23-1.37 2.52-1.37 2.69 0 3.18 1.77 3.18 4.08V17h-2.66v-3.52c0-.84-.02-1.92-1.17-1.92-1.17 0-1.35.91-1.35 1.86V17h-2.66V9.25Z"
            fill="white"
          />
        </Svg>
      );
    case "bing":
      return <BrandLogo brand="bing" decorative className={className} imageClassName={className} />;
    case "jira":
      return <BrandLogo brand="jira" decorative className={className} imageClassName={className} />;
    case "slack":
      return (
        <BrandLogo brand="slack" decorative className={className} imageClassName={className} />
      );
    case "teams":
      return (
        <BrandLogo brand="teams" decorative className={className} imageClassName={className} />
      );
    default:
      return null;
  }
}

export default function BrandMark({
  brand,
  className,
  markClassName,
  variant = "plain",
}: BrandMarkProps) {
  const mark = renderBrandMark(brand, markClassName);

  if (variant === "tile") {
    return (
      <span
        aria-label={BRAND_MARK_LABELS[brand]}
        className={cx(
          "inline-flex h-10 w-10 items-center justify-center rounded-[14px] border-0 bg-[#EEF1F6] shadow-(--shadow-inset)",
          className
        )}
        role="img"
      >
        {mark}
      </span>
    );
  }

  return (
    <span aria-label={BRAND_MARK_LABELS[brand]} className={className} role="img">
      {mark}
    </span>
  );
}
