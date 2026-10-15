"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import PromptSetup from "@/components/signal/PromptSetup";
import type { ScanPromptsState } from "@/hooks/useScanPrompts";

type AuditPromptsSectionProps = {
  prompts: ScanPromptsState;
  getAuthHeaders: () => Promise<Record<string, string>>;
};

/**
 * Prompts as part of scan setup (SIGV2-1176, rebuilt to the approved
 * prompt-setup UX in SIGV2-1194), between Context and Entity configuration on
 * the start-scan page, which is where Jake asked for it.
 *
 * Four properties of the design, and the reasons they are built this way:
 *
 * - **the list is the project's, pulled live.** Nothing here keeps a
 *   scan-local copy of the prompt set, so what the scan will measure and what
 *   the Prompts section shows cannot disagree.
 * - **at least one prompt is mandatory.** A project with no prompts leaves
 *   five separate surfaces empty, so the requirement is enforced where the
 *   customer can still act on it rather than discovered afterwards.
 * - **prompts can be added and reworded here, never removed.** Removal stays
 *   in the Prompts tab (the same component's manage mode), which is what
 *   stops two runs of the same project quietly measuring a different prompt
 *   set.
 * - **adding reuses the existing creation path.** `SignalAddPromptModal` is
 *   the same dialog as the AIO detail page's Prompts tab, so there is one set
 *   of validation rules, one plan-cap refusal that names the cap, the usage
 *   and the plan that raises it, and one creation endpoint. Creating a prompt
 *   already enqueues its own measurement (SIGV2-1182), so nothing here
 *   triggers or re-reports a run.
 *
 * A prompt added during setup persists on the project even if the scan is then
 * abandoned. Jake accepted that consequence; it is the price of the list being
 * the project's rather than the scan's, and it is stated here so nobody
 * "fixes" it later.
 */
export default function AuditPromptsSection({
  prompts: state,
  getAuthHeaders,
}: AuditPromptsSectionProps) {
  const { t } = useTranslation();

  const { projectId, isLoading, error, isPlanLocked, entitlements } = state;
  const planLabel = entitlements?.plan_label || entitlements?.plan || null;

  // Why there is no list to show, when there is none. Each of these is a state
  // the scan is NOT blocked on (see `useScanPrompts`), so each says what it is
  // rather than reading as a refusal.
  const unavailableReason =
    projectId === null
      ? t("signalStartCheck.prompts.noProject")
      : isLoading
        ? t("signalStartCheck.prompts.loading")
        : error
          ? t("signalStartCheck.prompts.unavailable")
          : isPlanLocked
            ? planLabel
              ? t("signalAddPrompt.locked", { plan: planLabel })
              : t("signalAddPrompt.lockedUnknownPlan")
            : null;

  return (
    <section
      id="audit-step-prompts"
      aria-label={t("signalStartCheck.prompts.heading")}
      className="rounded-[22px] border-0 bg-white px-[22px] py-5"
    >
      {unavailableReason !== null ? (
        <>
          <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold">
            {t("signalStartCheck.prompts.heading")}
          </h3>
          <p className="m-0 mb-4 text-[12.5px] leading-[1.5] text-(--t-3)">
            {t("signalStartCheck.prompts.description")}
          </p>
          <p className="m-0 text-xs leading-[1.5] text-(--t-3)" role="status">
            {unavailableReason}
          </p>
        </>
      ) : (
        <PromptSetup
          mode="scan"
          state={state}
          project={state.project}
          getAuthHeaders={getAuthHeaders}
        />
      )}
    </section>
  );
}
