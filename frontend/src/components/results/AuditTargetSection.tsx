"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Globe } from "lucide-react";

import AuditSection from "@/components/results/AuditSection";
import SignalAlert from "@/components/signal/SignalAlert";
import SignalInlineNote from "@/components/signal/SignalInlineNote";
import { cx } from "@/components/ui/utils";

type AuditTargetSectionProps = {
  auditForm: any;
  isStartDisabled: boolean;
  resolvedTargetUrl: string;
  cleanAuditError: (raw: string | null | undefined) => string;
};

/* `.wl`, `.winput` and `.wnote` from signal.css, which the approved page uses
   for every labelled field. */
const LABEL_CLASS =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const INPUT_CLASS =
  "field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const NOTE_CLASS = "mt-2 text-xs leading-[1.5] text-(--t-3)";

export default function AuditTargetSection({
  auditForm,
  isStartDisabled,
  resolvedTargetUrl,
  cleanAuditError,
}: AuditTargetSectionProps) {
  const { t } = useTranslation();
  const { form } = auditForm;
  const isBrandMode = form.auditTargetType === "brand";

  const urlErrorMessage =
    typeof auditForm.formErrors.targetUrl?.message === "string"
      ? auditForm.formErrors.targetUrl.message
      : typeof auditForm.formErrors.url?.message === "string"
        ? auditForm.formErrors.url.message
        : null;

  // The reachability line is the approved `#url-check` note. It only claims the
  // site is reachable for the address the preflight actually resolved, so an
  // edit retracts the claim instead of carrying it over.
  const typedUrl = resolvedTargetUrl.trim();
  const urlState: "idle" | "checking" | "resolved" | "unresolved" = auditForm.isPreflightChecking
    ? "checking"
    : typedUrl && auditForm.preflightVerifiedUrl === typedUrl
      ? "resolved"
      : typedUrl && auditForm.preflightError
        ? "unresolved"
        : "idle";

  return (
    <AuditSection
      id="audit-step-target"
      heading={t("signalStartCheck.target.heading")}
      description={t("signalStartCheck.target.description")}
    >
      <div className="mb-3">
        <span id="audit-target-type-label" className={LABEL_CLASS}>
          {t("signalStartCheck.target.typeLabel")}
        </span>
        <div
          role="group"
          aria-labelledby="audit-target-type-label"
          className="inline-flex gap-[2px] rounded-[9px] border-0 bg-[#EEF1F6] p-[3px]"
        >
          {(["website", "brand"] as const).map((targetType) => {
            const active = isBrandMode === (targetType === "brand");
            return (
              <button
                key={targetType}
                type="button"
                aria-pressed={active}
                disabled={isStartDisabled}
                onClick={() => auditForm.setFormValue("auditTargetType", targetType)}
                className={cx(
                  "rounded-[6px] border-none px-3 py-1.5 font-(family-name:--body-font) text-[12.5px] font-semibold transition-colors disabled:cursor-not-allowed max-md:min-h-11",
                  active
                    ? "bg-(--ink) text-white"
                    : "bg-transparent text-(--t-2) hover:text-(--t-1)"
                )}
              >
                {t(
                  targetType === "website"
                    ? "signalStartCheck.target.typeWebsite"
                    : "signalStartCheck.target.typeBrand"
                )}
              </button>
            );
          })}
        </div>
        <p className={NOTE_CLASS}>
          {t(
            isBrandMode
              ? "signalStartCheck.target.noteBrand"
              : "signalStartCheck.target.noteWebsite"
          )}
        </p>
      </div>

      <div className="mb-3">
        <label htmlFor="audit-url" className={LABEL_CLASS}>
          {t("signalStartCheck.target.urlLabel")}
        </label>
        {/* `.minp`: the icon and the field are one shell, so the focus ring
            belongs to the shell (see the composed-input rule in signal.css). */}
        <span className="flex h-11 items-center gap-[9px] rounded-[14px] border-0 bg-[#EEF1F6] px-3 focus-within:border-[#c9cef7]">
          <Globe className="h-4 w-4 shrink-0 text-(--t-3)" aria-hidden="true" />
          <input
            id="audit-url"
            type="text"
            value={isBrandMode ? form.targetUrl : form.url}
            onChange={(event) => {
              auditForm.setFormValue("url", event.target.value);
              auditForm.setFormValue("targetUrl", event.target.value);
            }}
            onBlur={() => auditForm.runUrlAutoDetection(false)}
            placeholder={t("signalStartCheck.target.urlPlaceholder")}
            disabled={isStartDisabled}
            className="min-w-0 flex-1 border-none bg-transparent font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) disabled:text-(--t-3)"
          />
        </span>
        {urlState === "checking" && (
          <p className={NOTE_CLASS}>{t("signalStartCheck.target.urlChecking")}</p>
        )}
        {/* The approved inline tier (`.note-inline`): feedback attached to the
            field that caused it, in the tone's own colour and with the tone's
            own glyph, and announced rather than printed in grey (SIGV2-1171). */}
        {urlState === "resolved" && (
          <SignalInlineNote tone="success">
            {t("signalStartCheck.target.urlResolved")}
          </SignalInlineNote>
        )}
        {urlState === "unresolved" && (
          <SignalInlineNote tone="danger">
            {t("signalStartCheck.target.urlUnresolved")}
          </SignalInlineNote>
        )}
        {urlErrorMessage && <SignalInlineNote tone="danger">{urlErrorMessage}</SignalInlineNote>}
      </div>

      <div>
        <label htmlFor="audit-target-name" className={LABEL_CLASS}>
          {t("signalStartCheck.target.nameLabel")}
        </label>
        <input
          id="audit-target-name"
          type="text"
          value={form.targetName}
          onChange={(event) => auditForm.setFormValue("targetName", event.target.value)}
          placeholder={t("signalStartCheck.target.namePlaceholder")}
          disabled={isStartDisabled}
          className={INPUT_CLASS}
        />
        <p className={NOTE_CLASS}>{t("signalStartCheck.target.nameHint")}</p>
        {typeof auditForm.formErrors.targetName?.message === "string" && (
          <SignalInlineNote tone="danger">
            {auditForm.formErrors.targetName.message}
          </SignalInlineNote>
        )}
      </div>

      {/* An unreadable target is a failure of the action, not a field hint, so
          it is the alert tier. It used to be a hand-rolled block with no role
          at all and its body in `--t-3` at 12px, which is how a reported
          failure reads as an empty section (SIGV2-1171). */}
      {(auditForm.preflightError || auditForm.preScanError) && (
        <SignalAlert tone="danger" title={t("signalAudit.target.unreadableTitle")} className="mt-4">
          {cleanAuditError(auditForm.preflightError || auditForm.preScanError)}
        </SignalAlert>
      )}
    </AuditSection>
  );
}
