"use client";

import React, { useId } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";

import { normalizeReportLanguage } from "@/lib/reportLanguages";
import { TARGET_MARKET_OPTIONS } from "@/lib/targetMarket";

import SettingsSection from "./SettingsSection";

export const ICP_ROLE_OPTIONS = [
  "CEO",
  "CMO",
  "CTO",
  "Head of Growth",
  "Marketing Manager",
  "Operations Manager",
];

export type ProjectSettingsState = {
  name: string;
  domainUrl: string;
  targetCountry: string;
  language: string;
  icpRoles: string[];
  painPoints: string;
  usp: string;
  priorityPulseTags: string;
  smeProfiles: string;
};

export type ProjectDetailsSectionProps = {
  form: ProjectSettingsState;
  onFormChange: (patch: Partial<ProjectSettingsState>) => void;
  customRole: string;
  onCustomRoleChange: (value: string) => void;
  onAddCustomRole: () => void;
  onToggleRole: (role: string) => void;
  onSave: () => void;
  onGenerate: () => void;
  saving: boolean;
  generating: boolean;
  disabled: boolean;
  missingFields: string[];
  message: string | null;
};

const REPORT_LANGUAGES: Array<{ value: string; label: string }> = [
  { value: "en", label: "English (US)" },
  { value: "es", label: "Spanish (ES/LATAM)" },
  { value: "fr", label: "French (FR)" },
  { value: "de", label: "German (DE)" },
  { value: "it", label: "Italian (IT)" },
  { value: "nl", label: "Dutch (NL)" },
  { value: "pt", label: "Portuguese (PT/BR)" },
  { value: "pl", label: "Polish (PL)" },
  { value: "sv", label: "Swedish (SV)" },
  { value: "ja", label: "Japanese (JP)" },
  { value: "zh", label: "Chinese (CN)" },
];

/**
 * Section 6. The brand facts every check is grounded in. The design calls this
 * "Node Settings"; the product calls things what they are, so it is the
 * project's details.
 */
export default function ProjectDetailsSection({
  form,
  onFormChange,
  customRole,
  onCustomRoleChange,
  onAddCustomRole,
  onToggleRole,
  onSave,
  onGenerate,
  saving,
  generating,
  disabled,
  missingFields,
  message,
}: ProjectDetailsSectionProps) {
  const { t } = useTranslation();
  const uid = useId();
  const field = (name: string) => `${uid}-${name}`;
  const busy = disabled || saving || generating || !form.name.trim();

  return (
    <SettingsSection
      variant="wsec"
      id="project-profile"
      title={t("signalProjectSettings.projectDetails.heading")}
      description={t("signalProjectSettings.projectDetails.description")}
      aside={
        <span className="rounded-[6px] bg-[rgba(147,51,234,0.1)] px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--purple)">
          {t("signalProjectSettings.projectDetails.chip")}
        </span>
      }
    >
      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="mb-4 last:mb-0">
          <label
            className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
            htmlFor={field("name")}
          >
            {t("signalProjectSettings.projectDetails.nameLabel")}
          </label>
          <input
            id={field("name")}
            className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
            type="text"
            placeholder={t("signalProjectSettings.projectDetails.namePlaceholder")}
            value={form.name}
            onChange={(event) => onFormChange({ name: event.target.value })}
          />
          <p className="mt-1.5 text-[12px] text-(--t-3)">
            {t("signalProjectSettings.projectDetails.nameHelp")}
          </p>
        </div>
        <div className="mb-4 last:mb-0">
          <label
            className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
            htmlFor={field("domain")}
          >
            {t("signalProjectSettings.projectDetails.domainLabel")}
          </label>
          <input
            id={field("domain")}
            className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
            type="text"
            placeholder={t("signalProjectSettings.projectDetails.domainPlaceholder")}
            value={form.domainUrl}
            onChange={(event) => onFormChange({ domainUrl: event.target.value })}
          />
          <p className="mt-1.5 text-[12px] text-(--t-3)">
            {t("signalProjectSettings.projectDetails.domainHelp")}
          </p>
        </div>
        <div className="mb-4 last:mb-0">
          <label
            className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
            htmlFor={field("market")}
          >
            {t("signalProjectSettings.projectDetails.marketLabel")}
          </label>
          <select
            id={field("market")}
            className="wselect-chevron field-focus-ring h-11 w-full cursor-pointer appearance-none rounded-[14px] border-0 bg-[#EEF1F6] pl-[13px] pr-[34px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none focus:bg-white"
            value={form.targetCountry}
            onChange={(event) => onFormChange({ targetCountry: event.target.value })}
          >
            {TARGET_MARKET_OPTIONS.map((country) => (
              <option key={country.code} value={country.code}>
                {country.name}
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-[12px] text-(--t-3)">
            {t("signalProjectSettings.projectDetails.marketHelp")}
          </p>
        </div>
      </div>

      <div className="mb-4">
        <label
          className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
          htmlFor={field("language")}
        >
          {t("signalProjectSettings.projectDetails.languageLabel")}
        </label>
        <select
          id={field("language")}
          className="wselect-chevron field-focus-ring h-11 w-full cursor-pointer appearance-none rounded-[14px] border-0 bg-[#EEF1F6] pl-[13px] pr-[34px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none focus:bg-white"
          value={normalizeReportLanguage(form.language)}
          onChange={(event) => onFormChange({ language: event.target.value })}
        >
          {REPORT_LANGUAGES.map((language) => (
            <option key={language.value} value={language.value}>
              {language.label}
            </option>
          ))}
        </select>
        <p className="mt-1.5 text-[12px] text-(--t-3)">
          {t("signalProjectSettings.projectDetails.languageHelp")}
        </p>
      </div>

      <div className="mb-4">
        <span
          className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
          id={field("roles-label")}
        >
          {t("signalProjectSettings.projectDetails.rolesLabel")}
        </span>
        <div className="flex flex-wrap gap-2" role="group" aria-labelledby={field("roles-label")}>
          {form.icpRoles.map((role) => (
            <button
              key={role}
              type="button"
              className="inline-flex h-8 items-center gap-2 rounded-[999px] border-0 pl-2.5 pr-1.5 text-[13px] font-semibold"
              aria-pressed={true}
              aria-label={t("signalProjectSettings.projectDetails.rolesSelected", { role })}
              onClick={() => onToggleRole(role)}
            >
              {role}
            </button>
          ))}
          {ICP_ROLE_OPTIONS.filter((role) => !form.icpRoles.includes(role)).map((role) => (
            <button
              key={role}
              type="button"
              className="inline-flex h-8 items-center gap-2 rounded-[999px] border-0 pl-2.5 pr-1.5 text-[13px] font-semibold"
              aria-pressed={false}
              aria-label={t("signalProjectSettings.projectDetails.rolesAvailable", { role })}
              onClick={() => onToggleRole(role)}
            >
              {role}
            </button>
          ))}
        </div>
        <div className="mt-2.5 flex max-w-[380px] gap-2">
          <label className="sr-only" htmlFor={field("custom-role")}>
            {t("signalProjectSettings.projectDetails.rolesAddLabel")}
          </label>
          <input
            id={field("custom-role")}
            className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
            type="text"
            placeholder={t("signalProjectSettings.projectDetails.rolesAddPlaceholder")}
            value={customRole}
            onChange={(event) => onCustomRoleChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                onAddCustomRole();
              }
            }}
          />
          <button
            type="button"
            className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] flex-none max-md:min-h-11"
            onClick={onAddCustomRole}
          >
            {t("signalProjectSettings.projectDetails.rolesAdd")}
          </button>
        </div>
        <p className="mt-2 text-[12px] text-(--t-3)">
          {t("signalProjectSettings.projectDetails.rolesHelp")}
        </p>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="mb-4 last:mb-0">
          <label
            className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
            htmlFor={field("pain")}
          >
            {t("signalProjectSettings.projectDetails.painLabel")}
          </label>
          <textarea
            id={field("pain")}
            className="field-focus-ring min-h-[76px] w-full resize-y rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-[11px] font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white"
            placeholder={t("signalProjectSettings.projectDetails.painPlaceholder")}
            value={form.painPoints}
            onChange={(event) => onFormChange({ painPoints: event.target.value })}
          />
        </div>
        <div className="mb-4 last:mb-0">
          <label
            className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
            htmlFor={field("usp")}
          >
            {t("signalProjectSettings.projectDetails.uspLabel")}
          </label>
          <textarea
            id={field("usp")}
            className="field-focus-ring min-h-[76px] w-full resize-y rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-[11px] font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white"
            placeholder={t("signalProjectSettings.projectDetails.uspPlaceholder")}
            value={form.usp}
            onChange={(event) => onFormChange({ usp: event.target.value })}
          />
        </div>
      </div>

      <div className="mb-4">
        <label
          className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
          htmlFor={field("tags")}
        >
          {t("signalProjectSettings.projectDetails.tagsLabel")}
        </label>
        <input
          id={field("tags")}
          className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
          type="text"
          placeholder={t("signalProjectSettings.projectDetails.tagsPlaceholder")}
          value={form.priorityPulseTags}
          onChange={(event) => onFormChange({ priorityPulseTags: event.target.value })}
        />
        <p className="mt-1.5 text-[12px] text-(--t-3)">
          {t("signalProjectSettings.projectDetails.tagsHelp")}
        </p>
      </div>

      <div className="mb-4">
        <label
          className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
          htmlFor={field("expertise")}
        >
          {t("signalProjectSettings.projectDetails.expertiseLabel")}
        </label>
        <textarea
          id={field("expertise")}
          className="field-focus-ring min-h-[76px] w-full resize-y rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-[11px] font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white"
          placeholder={t("signalProjectSettings.projectDetails.expertisePlaceholder")}
          value={form.smeProfiles}
          onChange={(event) => onFormChange({ smeProfiles: event.target.value })}
        />
        <p className="mt-1.5 text-[12px] text-(--t-3)">
          {t("signalProjectSettings.projectDetails.expertiseHelp")}
        </p>
      </div>

      <div className="flex justify-end gap-2.5">
        <button
          type="button"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] max-md:min-h-11"
          onClick={onGenerate}
          disabled={busy || missingFields.length > 0}
        >
          <Sparkles size={16} strokeWidth={2} aria-hidden="true" />
          {generating
            ? t("signalProjectSettings.projectDetails.generateBusy")
            : t("signalProjectSettings.projectDetails.generate")}
        </button>
        <button
          type="button"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black max-md:min-h-11"
          onClick={onSave}
          disabled={busy}
        >
          {saving
            ? t("signalProjectSettings.projectDetails.saveBusy")
            : t("signalProjectSettings.projectDetails.save")}
        </button>
      </div>

      <p className="mt-3 text-[12px] text-(--t-3)" role="status" aria-live="polite">
        {message}
      </p>
      <p className="mt-2 text-[12px] text-(--t-3)">
        {missingFields.length > 0
          ? t("signalProjectSettings.projectDetails.needed", { fields: missingFields.join(", ") })
          : t("signalProjectSettings.projectDetails.ready")}
      </p>
      <p className="mt-2 text-[12px] text-(--warn)">
        {t("signalProjectSettings.projectDetails.generateNote")}
      </p>
    </SettingsSection>
  );
}
