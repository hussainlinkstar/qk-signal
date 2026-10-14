/**
 * The scan launch intent (SIGV2-1159).
 *
 * The onboarding's last step starts the scan rather than opening the
 * start-scan form a second time (mockup: Signal Onboarding.html launches
 * Signal Audit Run.html). The question that then has to be answered safely is
 * "did the customer, in this tab, just ask for this scan?".
 *
 * It cannot be answered from the URL. Every query parameter is attacker
 * supplied, and the start-scan form prefills itself from `?url=`, so
 * comparing the form's target against the requested target compares a crafted
 * value with itself: `?url=attacker.tld&start=1` would have made a signed-in
 * victim's browser spend one of their scans on a target the attacker chose.
 *
 * `sessionStorage` answers it instead. It is same-origin, same-tab and
 * unreachable from a link, so an intent can only exist because our own code
 * wrote it. A crafted URL arrives with no intent and the setup form opens,
 * exactly as it does for anyone else following a prefilled link.
 *
 * Properties the audit page relies on:
 * - **single use**: the intent is removed before the run starts, so a reload
 *   or a remount cannot start a second scan;
 * - **short lived**: an intent older than `SCAN_LAUNCH_INTENT_TTL_MS` is
 *   discarded, so an abandoned onboarding cannot fire a scan on a later,
 *   unrelated visit to the page;
 * - **target bound**: it records the target it was created for, and the run
 *   starts only when the form holds that same target.
 *
 * Storage being unavailable (private modes that throw on write) degrades to
 * no intent, which means the setup form, never an unintended scan.
 */

export const SCAN_LAUNCH_INTENT_KEY = "signal.scan-launch-intent.v1";

/** How long a recorded intent stays startable. */
export const SCAN_LAUNCH_INTENT_TTL_MS = 2 * 60 * 1000;

export type ScanLaunchIntent = {
  /** The project the scan belongs to. */
  projectId: number;
  /** The target the customer confirmed, as entered. */
  target: string;
  /** `Date.now()` when the customer asked for the scan. */
  createdAt: number;
};

/** Host of a target, with scheme, `www.`, path and query removed. */
export function targetHost(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/^[a-z][a-z0-9+.-]*:\/\//, "")
    .replace(/^www\./, "")
    .replace(/[/?#].*$/, "");
}

/** Whether two targets name the same host. */
export function isSameTarget(left: string, right: string): boolean {
  const host = targetHost(right);
  return host.length > 0 && targetHost(left) === host;
}

function sessionStore(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * Record that the customer asked, in this tab, for this scan to start. Called
 * on the launch path only, never from anything a URL can reach.
 */
export function recordScanLaunchIntent(intent: { projectId: number; target: string }): void {
  const store = sessionStore();
  if (!store) return;
  const target = intent.target.trim();
  if (!target) return;
  try {
    store.setItem(
      SCAN_LAUNCH_INTENT_KEY,
      JSON.stringify({
        projectId: intent.projectId,
        target,
        createdAt: Date.now(),
      } satisfies ScanLaunchIntent)
    );
  } catch {
    // No intent recorded means the setup form opens. Nothing is lost but the
    // automatic start, and nothing unintended can happen.
  }
}

/** Forget any recorded intent. */
export function clearScanLaunchIntent(): void {
  const store = sessionStore();
  if (!store) return;
  try {
    store.removeItem(SCAN_LAUNCH_INTENT_KEY);
  } catch {
    // Nothing to do: a readable-but-unwritable store cannot be cleared, and
    // the expiry check below still refuses to act on a stale intent.
  }
}

/**
 * Read a recorded intent without consuming it, or null when there is none,
 * it cannot be parsed, or it has expired. An expired or malformed intent is
 * removed on the way out so it cannot be read again.
 *
 * Peeking rather than consuming matters: the page's first pass runs before
 * the form has been prefilled, and an intent consumed then would be gone
 * before the target it names could ever match. The caller consumes it with
 * `clearScanLaunchIntent()` immediately before starting the run.
 */
export function peekScanLaunchIntent(now: number = Date.now()): ScanLaunchIntent | null {
  const store = sessionStore();
  if (!store) return null;

  let raw: string | null = null;
  try {
    raw = store.getItem(SCAN_LAUNCH_INTENT_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearScanLaunchIntent();
    return null;
  }

  if (typeof parsed !== "object" || parsed === null) {
    clearScanLaunchIntent();
    return null;
  }

  const candidate = parsed as Partial<ScanLaunchIntent>;
  const projectId = candidate.projectId;
  const target = typeof candidate.target === "string" ? candidate.target.trim() : "";
  const createdAt = candidate.createdAt;

  if (
    typeof projectId !== "number" ||
    !Number.isInteger(projectId) ||
    projectId <= 0 ||
    !target ||
    typeof createdAt !== "number" ||
    !Number.isFinite(createdAt)
  ) {
    clearScanLaunchIntent();
    return null;
  }

  // Also refuses an intent stamped in the future, which a tampered record or
  // a clock change could produce.
  const age = now - createdAt;
  if (age < 0 || age > SCAN_LAUNCH_INTENT_TTL_MS) {
    clearScanLaunchIntent();
    return null;
  }

  return { projectId, target, createdAt };
}
