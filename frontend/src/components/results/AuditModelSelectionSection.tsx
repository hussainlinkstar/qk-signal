"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import AuditSection from "@/components/results/AuditSection";

/**
 * The approved "Models included with your plan" card (mockup: Signal
 * Audit.html, Oct-6 set, SIGV2-1188).
 *
 * The seven-pill engine list is gone: the design now tells the customer the
 * model set is a plan property, not a per-scan choice. It still renders no
 * control - choosing the models that run an audit is not a capability of any
 * plan in the catalogue, and `_strip_client_model_selection` discards any
 * submitted `provider` / `selected_models`. There is no capability key for it
 * either: SIGV2-1120 deleted `has_custom_ai_model_routing`, which had sat
 * `false` on all five canonical plans without a single runtime reader. The
 * bar is the design's `.prompt-summary` in its satisfied state; the warning
 * variant is unused until per-plan rosters land with the entitlement response.
 */
export default function AuditModelSelectionSection() {
  const { t } = useTranslation();

  return (
    <AuditSection
      id="audit-step-models"
      heading={t("signalStartCheck.models.heading")}
      description={t("signalStartCheck.models.description")}
    >
      <div className="flex flex-wrap items-center justify-between gap-2.5 rounded-[10px] border border-[#CEE9D7] bg-(--good-s) px-3.5 py-3 text-[12px] text-[#18683B]">
        <strong className="font-semibold">{t("signalStartCheck.models.managed")}</strong>
        <span>{t("signalStartCheck.models.managedScope")}</span>
      </div>
      <p className="my-2.5 text-[12px] leading-[1.7] text-(--t-2)">
        {t("signalStartCheck.models.planNote")}
      </p>
    </AuditSection>
  );
}
