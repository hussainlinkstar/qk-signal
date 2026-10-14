import { HttpRequestError } from "@/services/http";

/**
 * A scan launched without a selected project has to resolve or create one
 * first. When that step fails the customer used to be told "Failed to resolve
 * or create a project for this target", which names an internal step and
 * offers no action, and which sits directly under the remaining-scans line, so
 * it read as a refusal for being out of scans (SIGV2-1110).
 *
 * The failure is classified from the response status only. Server detail text
 * is never shown: it describes internals, not something a customer can act on.
 */

export type ProjectSetupFailureReason = "signedOut" | "noPermission" | "invalidTarget" | "generic";

export const PROJECT_SETUP_FAILURE_I18N_KEYS: Readonly<Record<ProjectSetupFailureReason, string>> =
  {
    signedOut: "signalStartCheck.launch.projectSetup.signedOut",
    noPermission: "signalStartCheck.launch.projectSetup.noPermission",
    invalidTarget: "signalStartCheck.launch.projectSetup.invalidTarget",
    generic: "signalStartCheck.launch.projectSetup.generic",
  };

export function resolveProjectSetupFailureReason(error: unknown): ProjectSetupFailureReason {
  const status = error instanceof HttpRequestError ? error.status : null;

  if (status === 401) return "signedOut";
  if (status === 403) return "noPermission";
  if (status === 400 || status === 409 || status === 422) return "invalidTarget";
  return "generic";
}

export function resolveProjectSetupFailureKey(error: unknown): string {
  return PROJECT_SETUP_FAILURE_I18N_KEYS[resolveProjectSetupFailureReason(error)];
}
