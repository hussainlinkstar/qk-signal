"use client";

import React, { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Pencil } from "lucide-react";

import AuditSection from "@/components/results/AuditSection";
import CategoryCombobox from "@/components/results/CategoryCombobox";
import { EU_AUDIT_LANGUAGES } from "@/constants/auditLanguages";

type AuditContextSectionProps = {
  auditForm: any;
  auditRunner: any;
};

const LABEL_CLASS =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const FIELD_CLASS =
  "field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";

export default function AuditContextSection({ auditForm, auditRunner }: AuditContextSectionProps) {
  const { t } = useTranslation();
  const { form } = auditForm;

  const renderDetectedBadge = useCallback(
    (field: "language" | "market" | "category") => {
      if (!auditForm.preScanResult) return null;

      if (auditForm.manualOverrides[field]) {
        return (
          <span className="rounded-md bg-(--line-2) px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
            {t("signalStartCheck.context.editing")}
          </span>
        );
      }

      return (
        <button
          type="button"
          onClick={() =>
            auditForm.setManualOverrides((prev: any) => ({
              ...prev,
              [field]: true,
            }))
          }
          className="inline-flex h-6 cursor-pointer items-center gap-1 rounded-full border-0 bg-[#EEF1F6] px-2 font-(family-name:--body-font) text-xs font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
          title={t("signalStartCheck.context.editTitle")}
        >
          <Pencil className="h-3 w-3" />
          {t("signalStartCheck.context.edit")}
        </button>
      );
    },
    [auditForm, t]
  );

  const fieldDisabled = (field: "language" | "market" | "category") =>
    auditRunner.isLoading ||
    auditRunner.isPolling ||
    (!!auditForm.preScanResult && !auditForm.manualOverrides[field]);

  const summaryParts = [
    form.category?.trim(),
    form.language?.trim(),
    form.market?.trim() || form.targetMarket?.trim(),
  ].filter(Boolean);

  return (
    <AuditSection
      id="audit-step-context"
      heading={t("signalStartCheck.context.heading")}
      description={t("signalStartCheck.context.description")}
      collapsible
      defaultOpen={false}
      summary={
        summaryParts.length
          ? summaryParts.join(" · ")
          : t("signalStartCheck.context.description")
      }
    >
      <div className="mb-3">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="audit-category" className={LABEL_CLASS}>
            {t("signalStartCheck.context.categoryLabel")}
          </label>
          {renderDetectedBadge("category")}
        </div>
        <CategoryCombobox
          value={form.category}
          onChange={(value) => {
            auditForm.setManualOverrides((prev: any) => ({ ...prev, category: true }));
            auditForm.setFormValue("category", value);
          }}
          disabled={fieldDisabled("category")}
          isDetecting={auditForm.isCategoryDetecting}
          aiSuggestion={auditForm.aiSuggestedCategory}
        />
        {/* The approved note under the first context field. The per-field
            badge above is how "click to change it" is actually done. */}
        <p className="mt-2 text-xs leading-[1.5] text-(--t-3)">
          {t("signalStartCheck.context.filledFromSite")}
        </p>
      </div>

      <div className="mb-3">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="audit-market" className={LABEL_CLASS}>
            {t("signalStartCheck.context.marketLabel")}
          </label>
          {renderDetectedBadge("market")}
        </div>
        <input
          id="audit-market"
          type="text"
          value={form.market}
          onChange={(event) => {
            auditForm.setManualOverrides((prev: any) => ({ ...prev, market: true }));
            auditForm.setFormValue("market", event.target.value);
          }}
          placeholder={t("signalStartCheck.context.marketPlaceholder")}
          disabled={fieldDisabled("market")}
          className={FIELD_CLASS}
        />
      </div>

      <div>
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="audit-language" className={LABEL_CLASS}>
            {t("signalStartCheck.context.languageLabel")}
          </label>
          {renderDetectedBadge("language")}
        </div>
        <select
          id="audit-language"
          value={
            EU_AUDIT_LANGUAGES.some((lang) => lang.code === form.language) ? form.language : "en"
          }
          onChange={(event) => {
            auditForm.setManualOverrides((prev: any) => ({ ...prev, language: true }));
            auditForm.setFormValue("language", event.target.value);
          }}
          disabled={fieldDisabled("language")}
          className={`${FIELD_CLASS} wselect-chevron cursor-pointer appearance-none pr-[34px]`}
        >
          {EU_AUDIT_LANGUAGES.map((lang) => (
            <option key={lang.code} value={lang.code}>
              {lang.label}
            </option>
          ))}
        </select>
      </div>

      {/* The approved page assumes the context arrives filled in from the site,
          which the blur-triggered read already does. This is the explicit
          re-read for a target whose site has changed; it is not a separate
          analysis step and it consumes no scan. */}
      <button
        type="button"
        onClick={() => auditForm.runUrlAutoDetection(true)}
        disabled={auditForm.isPreScanning || auditRunner.isLoading || auditRunner.isPolling}
        className="mt-4 inline-flex cursor-pointer items-center gap-1.5 border-none bg-transparent p-0 text-xs font-semibold text-(--t-2) underline hover:text-(--t-1) disabled:cursor-not-allowed"
      >
        {auditForm.isPreScanning ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin" />
            {t("signalStartCheck.context.refilling")}
          </>
        ) : (
          t("signalStartCheck.context.refill")
        )}
      </button>
    </AuditSection>
  );
}
