/**
 * The one launch path from anywhere in the product to a running scan
 * (SIGV2-1159, SIGV2-1184).
 *
 * Two separate things happen when a control launches a scan, and the
 * distinction is the security boundary (see `scanLaunchIntent.ts`):
 *
 * - the href only **prefills** the start-scan form and carries nothing
 *   privileged: anyone can send that link and it opens the form;
 * - the recorded launch intent is the **authority** to start, and lives in
 *   this tab's `sessionStorage` where no link can reach it.
 *
 * They are separate functions here because a link's href is computed while the
 * page renders, and recording the authority then would mean that merely
 * looking at a dashboard authorises a scan. `authorizeScanLaunch` belongs in
 * the click handler, nowhere else.
 *
 * A target that cannot be resolved records no authority at all, so the form
 * opens as it always did and the customer completes it themselves.
 */

import { recordScanLaunchIntent } from "@/lib/scanLaunchIntent";

export type ScanLaunchTarget = {
  /** The address to scan, as the project or its last audit holds it. */
  url?: string | null;
  /** How the target is labelled on the report. */
  name?: string | null;
  /** `brand` when the run being repeated was a brand audit. */
  targetType?: "website" | "brand" | null;
};

/** The target as the launch path uses it: trimmed, with blanks dropped. */
function resolveTarget(target: ScanLaunchTarget): {
  url: string;
  name: string;
  targetType: "website" | "brand" | null;
} {
  return {
    url: (target.url ?? "").trim(),
    name: (target.name ?? "").trim(),
    targetType:
      target.targetType === "brand" || target.targetType === "website" ? target.targetType : null,
  };
}

/**
 * The start-scan URL for this project and target. Pure: it records nothing and
 * grants nothing, so it is safe to compute during render.
 */
export function buildScanLaunchHref(
  projectId: number | string,
  target: ScanLaunchTarget = {},
  extraParams: Record<string, string> = {}
): string {
  const { url, name, targetType } = resolveTarget(target);
  const params = new URLSearchParams({ projectId: String(projectId) });
  for (const [key, value] of Object.entries(extraParams)) {
    if (value) params.set(key, value);
  }
  if (url) {
    params.set("url", url);
    if (name) params.set("targetName", name);
  }
  if (targetType) params.set("targetType", targetType);
  return `/dashboard/audit?${params.toString()}`;
}

/**
 * Record that the customer asked, in this tab, for this scan to run. Call this
 * from the click handler of the control they pressed, never during render.
 *
 * The audit page's own guards still decide whether the run starts: signed in,
 * nothing already attached, the form not blocked, and the form's target still
 * the one named here. Nothing is recorded without a resolvable target.
 */
export function authorizeScanLaunch(projectId: number, target: ScanLaunchTarget): void {
  const { url } = resolveTarget(target);
  if (!url || !Number.isInteger(projectId) || projectId <= 0) return;
  recordScanLaunchIntent({ projectId, target: url });
}

/**
 * Authorise and build in one call, for a launch that navigates
 * programmatically (the onboarding's "Run my first scan" pushes the returned
 * href).
 *
 * SIGV2-1256: this is for a control that has already collected the scan's
 * configuration, which in practice means the onboarding wizard and nothing
 * else. A control that only knows the target, such as the project
 * dashboard's Rescan, uses `buildScanLaunchHref` alone and authorises
 * nothing: the customer arrives at the prefilled setup form and starts the
 * run themselves, rather than having a scan spent on one click with nothing
 * left to choose.
 */
export function beginScanLaunch(
  projectId: number,
  target: ScanLaunchTarget = {},
  extraParams: Record<string, string> = {}
): string {
  authorizeScanLaunch(projectId, target);
  return buildScanLaunchHref(projectId, target, extraParams);
}
