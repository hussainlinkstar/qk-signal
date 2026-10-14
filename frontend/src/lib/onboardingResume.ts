/**
 * Where onboarding was when it left the app (SIGV2-1220).
 *
 * Connecting GA4 at step 4 is a full browser navigation to Google and back.
 * Everything the wizard held lived in React state, so it was gone by the time
 * the customer returned, and the backend's return landed in the Connections
 * Hub rather than the wizard. Worse, the overview page treats "a project
 * exists" as "onboarding finished", so the wizard did not reopen at all: the
 * remaining steps became unreachable after connecting GA4.
 *
 * This records the three facts needed to carry on: which workspace, which
 * project, and which step. It is written immediately before the redirect and
 * consumed when the wizard closes.
 *
 * `sessionStorage` rather than the URL or `localStorage`:
 * - the URL is attacker supplied, and a crafted link must not be able to put
 *   a signed-in customer back into a wizard pointed at a project id it names;
 * - it is same-tab, so it survives the OAuth round trip in that tab and is
 *   invisible to every other one;
 * - it is short lived by nature, and the TTL below bounds it further so an
 *   abandoned setup cannot reopen the wizard on a later visit.
 *
 * The recorded workspace is checked against the active one on read. A project
 * belongs to the workspace it was created in, so a context from another
 * workspace is dropped rather than resumed against whatever is current, the
 * same refusal-over-substitution rule SIGV2-1207 applied to the connect
 * redirect.
 */

export const ONBOARDING_RESUME_KEY = "signal.onboarding-resume.v1";

/** How long a recorded context stays resumable: one OAuth round trip. */
export const ONBOARDING_RESUME_TTL_MS = 30 * 60 * 1000;

/** The wizard's step range. Anything outside it is not a step. */
export const ONBOARDING_FIRST_STEP = 1;
export const ONBOARDING_LAST_STEP = 5;

export type OnboardingResume = {
  /** The workspace the setup belongs to, when one was active. */
  workspaceId: number | null;
  /** The project created at step 2, or null before it exists. */
  projectId: number | null;
  /** The step to resume at. */
  step: number;
  /** `Date.now()` when the context was recorded. */
  createdAt: number;
};

function sessionStore(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

const isStep = (value: unknown): value is number =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value >= ONBOARDING_FIRST_STEP &&
  value <= ONBOARDING_LAST_STEP;

const isOptionalId = (value: unknown): value is number | null =>
  value === null ||
  value === undefined ||
  (typeof value === "number" && Number.isInteger(value) && value > 0);

/** Forget any recorded context. */
export function clearOnboardingResume(): void {
  const store = sessionStore();
  if (!store) return;
  try {
    store.removeItem(ONBOARDING_RESUME_KEY);
  } catch {
    // A readable-but-unwritable store cannot be cleared; the TTL and the
    // validation on read still refuse to act on a stale record.
  }
}

/**
 * Record where to carry on from. Called on the leave-the-app path only.
 * An out-of-range step records nothing: there is no step to come back to.
 */
export function recordOnboardingResume(context: {
  workspaceId: number | null;
  projectId: number | null;
  step: number;
}): void {
  const store = sessionStore();
  if (!store) return;
  if (!isStep(context.step)) return;
  try {
    store.setItem(
      ONBOARDING_RESUME_KEY,
      JSON.stringify({
        workspaceId: isOptionalId(context.workspaceId) ? (context.workspaceId ?? null) : null,
        projectId: isOptionalId(context.projectId) ? (context.projectId ?? null) : null,
        step: context.step,
        createdAt: Date.now(),
      } satisfies OnboardingResume)
    );
  } catch {
    // No context recorded means the customer lands on the overview with the
    // project they already created. Nothing is lost but the automatic resume.
  }
}

/**
 * Read the recorded context, or null when there is none, it cannot be
 * trusted, it has expired, or it belongs to a different workspace. Anything
 * rejected is removed on the way out so it cannot be read again.
 *
 * Reading does not consume: the page reads on every render pass and consumes
 * explicitly with `clearOnboardingResume()` when the wizard closes.
 */
export function readOnboardingResume(
  options: { now?: number; activeWorkspaceId?: number | null } = {}
): OnboardingResume | null {
  const store = sessionStore();
  if (!store) return null;

  let raw: string | null = null;
  try {
    raw = store.getItem(ONBOARDING_RESUME_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearOnboardingResume();
    return null;
  }

  if (typeof parsed !== "object" || parsed === null) {
    clearOnboardingResume();
    return null;
  }

  const candidate = parsed as Partial<OnboardingResume>;
  const { workspaceId, projectId, step, createdAt } = candidate;

  if (
    !isStep(step) ||
    !isOptionalId(projectId) ||
    !isOptionalId(workspaceId) ||
    typeof createdAt !== "number" ||
    !Number.isFinite(createdAt)
  ) {
    clearOnboardingResume();
    return null;
  }

  // A context stamped in the future comes from a tampered record or a clock
  // change, and is no more trustworthy than an expired one.
  const age = (options.now ?? Date.now()) - createdAt;
  if (age < 0 || age > ONBOARDING_RESUME_TTL_MS) {
    clearOnboardingResume();
    return null;
  }

  // Recorded against a workspace that is no longer the active one: the
  // project named here is not reachable from here. Left in place rather than
  // cleared, so switching back to that workspace still resumes it.
  const activeWorkspaceId = options.activeWorkspaceId;
  if (
    typeof workspaceId === "number" &&
    typeof activeWorkspaceId === "number" &&
    workspaceId !== activeWorkspaceId
  ) {
    return null;
  }

  return {
    workspaceId: workspaceId ?? null,
    projectId: projectId ?? null,
    step,
    createdAt,
  };
}
