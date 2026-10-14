"use client";

import { usePathname } from "next/navigation";
import { BASE_PATH } from "@/lib/basePath";

/**
 * qiko-core decorative layer (fixed violet/cyan orbs over an indigo grid,
 * z-index:-1). It belongs to the dark brand theme and must not render on
 * Signal surfaces, whose approved canvas is a flat #F2F4FB: the orbs leaked
 * into the gutter around the floating card. The root layout is shared across
 * route groups, so the Signal check runs client-side on the pathname: the
 * dashboard tree and the status-shell routes render nothing here, while
 * admin/auth/marketing/portal/connect/gate keep the brand backdrop.
 */
const SIGNAL_PREFIXES = ["/dashboard", "/maintenance"];

export default function QikoBackdrop() {
  const pathname = usePathname() ?? "";
  const stripped = pathname.startsWith(BASE_PATH)
    ? pathname.slice(BASE_PATH.length) || "/"
    : pathname;
  if (SIGNAL_PREFIXES.some((p) => stripped === p || stripped.startsWith(`${p}/`))) {
    return null;
  }
  return (
    <>
      <div className="qiko-grid" aria-hidden="true" />
      <div className="qiko-orbs" aria-hidden="true">
        <i className="o1 animate-float" />
        <i className="o2 animate-float-delayed" />
        <i className="o3 animate-pulse-glow" />
      </div>
    </>
  );
}
