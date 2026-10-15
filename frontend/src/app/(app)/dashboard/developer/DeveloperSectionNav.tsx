"use client";

import Link from "next/link";
import React from "react";
import { usePathname } from "next/navigation";
import { BookOpen, ExternalLink, FileText, Radar } from "lucide-react";

import { cx } from "@/components/ui/utils";

const items = [
  {
    href: "/dashboard/developer",
    label: "Hub",
    icon: BookOpen,
    external: false,
    match: (pathname: string) => pathname === "/dashboard/developer",
  },
  {
    href: "/dashboard/developer/docs",
    label: "Quick Start",
    icon: Radar,
    external: false,
    match: (pathname: string) => pathname === "/dashboard/developer/docs",
  },
  {
    href: "/api-reference",
    label: "API Reference",
    icon: FileText,
    external: true,
    match: () => false,
  },
] as const;

const tabClass = "rounded px-3 py-1.5 text-sm font-medium transition-colors";

export default function DeveloperSectionNav() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 z-10 -mx-6 border-b border-(--border) px-6 py-3 backdrop-blur-xs">
      <div className="flex gap-1">
        {items.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cx(
                tabClass,
                active
                  ? "border-0 bg-[#E8F1FF] text-[#1D4ED8]"
                  : "text-(--muted-foreground) hover:bg-(--surface-subtle) hover:text-(--foreground)"
              )}
              aria-current={active ? "page" : undefined}
            >
              <span className="flex items-center gap-2">
                <Icon className="h-3.5 w-3.5" />
                {item.label}
                {item.external && <ExternalLink className="h-3 w-3 opacity-50" />}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
