import React, { type ReactNode } from "react";
import { type LucideIcon } from "lucide-react";

import { cx } from "@/components/ui/utils";

type DashboardPageIntroProps = {
  /** Optional. Nav already shows the page icon; omit the pastel tile (UI/UX Fixes). */
  icon?: LucideIcon;
  title: string;
  /** Retained for API compatibility; unused when the icon tile is hidden. */
  color?: string;
  children?: ReactNode;
  className?: string;
};

/**
 * Page title + subtitle. Icon tile is opt-in — Settings / Billing / Profile /
 * Start a scan omit it so the H1 is not doubled with the nav icon.
 */
export default function DashboardPageIntro({
  icon: Icon,
  title,
  children,
  className,
}: DashboardPageIntroProps) {
  return (
    <div className={cx("flex items-center gap-[14px]", className)}>
      {Icon ? (
        <div className="flex h-[46px] w-[46px] flex-none items-center justify-center rounded-[13px] bg-[rgba(147,51,234,0.1)] text-(--purple) [&_svg]:h-[23px] [&_svg]:w-[23px] [&_svg]:[stroke-width:1.9]">
          <Icon />
        </div>
      ) : null}
      <div>
        <h1 className="m-0 font-(family-name:--disp) text-[24px] font-extrabold leading-[1.25] tracking-[-0.02em]">
          {title.trim().replace(/\s+/g, " ")}
        </h1>
        {children ? (
          <div className="mt-2 max-w-[640px] text-[13px] leading-[1.5] text-(--t-2)">
            {children}
          </div>
        ) : null}
      </div>
    </div>
  );
}
