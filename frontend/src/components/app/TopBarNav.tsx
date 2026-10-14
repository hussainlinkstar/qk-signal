import React from "react";
import Link from "next/link";
import { getHeaderNavLinkClassName } from "@/components/navigation/headerNavStyles";
import { cx } from "@/components/ui/utils";

type TopBarNavProps = {
  children: React.ReactNode;
  className?: string;
};

type TopBarNavLinkProps = {
  href: string;
  children: React.ReactNode;
  className?: string;
};

export function TopBarNav({ children, className }: TopBarNavProps) {
  return (
    <nav
      className={cx(
        "hidden items-center gap-5 text-sm font-medium text-(--text-soft) md:flex",
        className
      )}
    >
      {children}
    </nav>
  );
}

export function TopBarNavLink({ href, children, className }: TopBarNavLinkProps) {
  return (
    <Link className={getHeaderNavLinkClassName({ className })} href={href}>
      {children}
    </Link>
  );
}
