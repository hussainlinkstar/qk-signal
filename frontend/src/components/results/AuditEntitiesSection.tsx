"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "motion/react";
import { Plus, Sparkles, X } from "lucide-react";

import AuditSection from "@/components/results/AuditSection";

type AuditEntitiesSectionProps = {
  auditForm: any;
  isStartDisabled: boolean;
  entitySummary: any;
};

export default function AuditEntitiesSection({
  auditForm,
  isStartDisabled,
  entitySummary,
}: AuditEntitiesSectionProps) {
  const { t } = useTranslation();
  const { form } = auditForm;

  // `.fstat` order is the approved one: names, strong matches, average match,
  // type known. Every value comes from the resolved entity set, and a missing
  // average reads as no value rather than 0%.
  const stats = [
    { label: t("signalStartCheck.entities.namesAdded"), value: String(entitySummary.total) },
    {
      label: t("signalStartCheck.entities.strongMatches"),
      value: String(entitySummary.highConfidence),
    },
    {
      label: t("signalStartCheck.entities.averageMatch"),
      value:
        typeof entitySummary.avgConfidence === "number"
          ? `${entitySummary.avgConfidence}%`
          : t("signalStartCheck.entities.noValue"),
    },
    { label: t("signalStartCheck.entities.typeKnown"), value: String(entitySummary.categorized) },
  ];

  return (
    <AuditSection
      id="audit-step-entities"
      heading={t("signalStartCheck.entities.heading")}
      description={t("signalStartCheck.entities.description")}
    >
      <div className="mb-3">
        <label
          htmlFor="audit-entities"
          className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
        >
          {t("signalStartCheck.entities.inputLabel")}
        </label>
        {/* `.minp` with the plus icon, as the approved entity field is drawn. */}
        <span className="flex h-11 items-center gap-[9px] rounded-[14px] border-0 bg-[#EEF1F6] px-3 focus-within:border-[#c9cef7]">
          <Plus className="h-4 w-4 shrink-0 text-(--t-3)" aria-hidden="true" />
          <input
            id="audit-entities"
            value={form.entityInput}
            onChange={auditForm.handleEntityInputChange}
            onKeyDown={auditForm.handleEntityInputKeyDown}
            onBlur={auditForm.handleEntityInputBlur}
            placeholder={t(
              form.entities.length
                ? "signalStartCheck.entities.inputPlaceholder"
                : "signalStartCheck.entities.firstPlaceholder"
            )}
            disabled={isStartDisabled}
            className="min-w-0 flex-1 border-none bg-transparent font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) disabled:text-(--t-3)"
          />
        </span>
      </div>

      {(form.entities.length > 0 || auditForm.entitySuggestions.length > 0) && (
        <div className="mb-3 flex flex-wrap items-center gap-2.5">
          <AnimatePresence initial={false}>
            {form.entities.map((entity: string) => (
              <motion.span
                key={entity}
                layout
                initial={{ opacity: 0, scale: 0.9, y: 5 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.9, y: 5 }}
                className="inline-flex items-center gap-1.5 rounded-md bg-[rgba(147,51,234,0.1)] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--purple)"
              >
                {entity}
                <button
                  type="button"
                  aria-label={t("signalStartCheck.entities.removeName", { name: entity })}
                  className="flex h-3.5 w-3.5 cursor-pointer items-center justify-center rounded-full text-(--purple)"
                  onClick={() => auditForm.removeEntity(entity)}
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </motion.span>
            ))}
          </AnimatePresence>
          {auditForm.entitySuggestions.length > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-(--t-3)">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              {t("signalStartCheck.entities.suggestionsLabel")}
            </span>
          )}
          {auditForm.entitySuggestions.map((suggestion: any) => (
            <button
              key={`${suggestion.name}-${suggestion.type}`}
              type="button"
              onClick={() => auditForm.handleAddSuggestion(suggestion)}
              className="inline-flex cursor-pointer items-center rounded-md bg-(--line-2) px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--t-2) hover:text-(--t-1)"
            >
              {suggestion.name}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-[14px] max-md:*:w-full max-md:*:min-w-0 md:flex-row">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="flex-1 rounded-xl border-0 bg-[#EEF1F6] px-[18px] py-4"
          >
            <div className="mb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
              {stat.label}
            </div>
            <div className="font-(family-name:--disp) text-2xl font-extrabold tracking-[-0.02em]">
              {stat.value}
            </div>
          </div>
        ))}
      </div>
    </AuditSection>
  );
}
