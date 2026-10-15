"use client";

import Link from "next/link";
import React from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import AuditSection from "@/components/results/AuditSection";
import SignalAlert from "@/components/signal/SignalAlert";
import { cx } from "@/components/ui/utils";
import { formatTierDurationRange, type TierDurationsMap } from "@/hooks/useTierDurations";

type AuditLaunchSectionProps = {
  auditForm: any;
  auditRunner: any;
  isStartDisabled: boolean;
  /**
   * Measured per-tier durations, read once by the page (SIGV2-1177). The same
   * map the depth table renders, so the sentence and the column cannot
   * disagree. Null or a missing tier means no figure is stated.
   */
  tierDurations: TierDurationsMap | null;
};

/**
 * The approved Launch section (mockup: Signal Audit.html): the typical runtime
 * for the chosen depth and the leave-the-page promise in one sentence, then
 * Cancel and Start the audit.
 *
 * The figure is the measured p25..p75 range the page fetched once and handed
 * to both this sentence and the depth table, so the two cannot state
 * different numbers (SIGV2-1177). A depth with no publishable measurement
 * keeps the promise and claims no duration; no invented number appears.
 *
 * No progress surface lives here. Once the run starts the whole page switches
 * to the run view, which reports per-stage state words and deliberately no
 * percentage.
 *
 * A start that is refused reports itself here, next to the button that was
 * pressed (SIGV2-1171). `useAuditRunner` has always produced that message -
 * validation, a missing target, a failed preflight, a project that could not
 * be created, an ended session - and no surface rendered it, so the customer
 * pressed Start and got silence. The approved start-scan page draws no alert
 * of its own, so the anatomy is the component sheet's generic `.alert`
 * (Signal Components.html, `#sec-alerts`) via `SignalAlert`; the placement is
 * a question for Jake, recorded on the ticket.
 */
export default function AuditLaunchSection({
  auditForm,
  auditRunner,
  isStartDisabled,
  tierDurations,
}: AuditLaunchSectionProps) {
  const { t } = useTranslation();

  const durationFigure = tierDurations?.[auditForm.form?.tier ?? ""] ?? null;
  const description = durationFigure
    ? t("signalStartCheck.launch.description", {
        time: formatTierDurationRange(durationFigure),
      })
    : t("signalStartCheck.launch.descriptionNoEstimate");

  const startLabel = auditForm.isPreflightChecking
    ? t("signalStartCheck.launch.checkingAddress")
    : auditRunner.isLoading
      ? t("signalStartCheck.launch.starting")
      : auditRunner.isPolling
        ? t("signalStartCheck.launch.running")
        : t("signalStartCheck.launch.start");

  const startFailure =
    typeof auditRunner.error === "string" && auditRunner.error.trim() ? auditRunner.error : null;
  const isDuplicateRun = Boolean(auditRunner.isDuplicateAudit);

  return (
    <AuditSection
      id="audit-step-launch"
      heading={t("signalStartCheck.launch.heading")}
      description={description}
    >
      {isDuplicateRun ? (
        <SignalAlert
          tone="warning"
          title={t("signalStartCheck.launch.duplicateTitle")}
          className="mb-3"
        >
          {t("signalStartCheck.launch.duplicateBody")}
        </SignalAlert>
      ) : startFailure ? (
        <SignalAlert
          tone="danger"
          title={t("signalStartCheck.launch.failedTitle")}
          className="mb-3"
        >
          {startFailure}
        </SignalAlert>
      ) : null}

      {/* SIGV2-1171: a failed draft autosave is the one failure that can cost
          the customer work, so it reports persistently here with the other
          launch refusals and says what to do, rather than fading as a toast.
          A successful save stays silent by the same decision. */}
      {auditForm.draftSaveFailed ? (
        <SignalAlert
          tone="warning"
          title={t("signalStartCheck.launch.draftSaveFailedTitle")}
          className="mb-3"
        >
          {t("signalStartCheck.launch.draftSaveFailedBody")}
        </SignalAlert>
      ) : null}

      <div className="flex flex-wrap items-center gap-2.5">
        <Link
          href="/dashboard"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
        >
          {t("signalStartCheck.launch.cancel")}
        </Link>
        <button
          type="submit"
          disabled={isStartDisabled}
          className={cx(
            "inline-flex h-[38px] cursor-pointer items-center justify-center gap-2 rounded-[10px] border px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold",
            !isStartDisabled
              ? "border-(--ink) bg-(--ink) text-white hover:bg-black"
              : "border-(--line) bg-(--panel) text-(--t-1)"
          )}
        >
          {(auditRunner.isLoading || auditForm.isPreflightChecking || auditRunner.isPolling) && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          {startLabel}
        </button>
      </div>
    </AuditSection>
  );
}
