"use client";

import Link from "next/link";
import { useEffect } from "react";
import { ChevronLeft } from "lucide-react";

import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";

/**
 * signal-MVP workspace-scope content area: the page identity lives in the
 * shared `.top` bar (registered via WorkspacePageHeaderContext), so this
 * frame renders no header of its own, only the approved `.wrap` padding
 * (18/32/12) and an optional `.backlink` row above the page content.
 */
export default function WorkspacePageFrame({
  title,
  meta,
  backHref,
  backLabel,
  children,
}: {
  title?: string;
  meta?: string;
  backHref?: string;
  backLabel?: string;
  children: React.ReactNode;
}) {
  const { setHeader } = useWorkspacePageHeader();

  useEffect(() => {
    setHeader(title || meta ? { title, meta } : null);
    return () => setHeader(null);
  }, [setHeader, title, meta]);

  return (
    // signal-MVP `body[data-scope="workspace"] .wrap`: padding 18/32/12.
    // The negative margins neutralise the shell <main> padding so the wrap
    // padding alone decides the offset, exactly like the mockup.
    <div
      data-workspace-page
      className="-mx-3 -mt-3 -mb-24 flex min-w-0 flex-1 flex-col gap-[18px] px-3 pt-[18px] pb-3 leading-[normal] md:-mx-8 md:-mt-5 md:-mb-3.5 md:px-8"
    >
      {backHref && backLabel ? (
        <Link
          href={backHref}
          className="inline-flex w-fit items-center gap-[7px] text-[13px] font-semibold text-(--t-2) hover:text-(--t-1) max-md:min-h-11"
        >
          <ChevronLeft aria-hidden="true" size={16} />
          {backLabel}
        </Link>
      ) : null}
      {children}
    </div>
  );
}
