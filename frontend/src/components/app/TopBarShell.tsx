import React from "react";
import { cx } from "@/components/ui/utils";

type TopBarShellProps = {
  logo: React.ReactNode;
  nav: React.ReactNode;
  actions: React.ReactNode;
  className?: string;
  containerClassName?: string;
};

export default function TopBarShell({
  logo,
  nav,
  actions,
  className,
  containerClassName,
}: TopBarShellProps) {
  return (
    <header
      data-app-topbar
      className={cx("glass-surface sticky top-0 z-topbar px-5 py-3 shadow-sm md:px-8", className)}
    >
      <div
        className={cx(
          "mx-auto flex max-w-7xl items-center justify-between gap-4",
          containerClassName
        )}
      >
        <div className="min-w-0">{logo}</div>
        {nav}
        <div className="shrink-0 flex items-center gap-3">{actions}</div>
      </div>
    </header>
  );
}
