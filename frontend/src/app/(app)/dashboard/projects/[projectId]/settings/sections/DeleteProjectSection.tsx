"use client";

import React, { useId } from "react";
import { useTranslation } from "react-i18next";

import SettingsSection from "./SettingsSection";

export type DeleteProjectSectionProps = {
  projectName: string;
  confirmName: string;
  onConfirmNameChange: (value: string) => void;
  onDelete: () => void;
  deleting: boolean;
  disabled: boolean;
  message: string | null;
};

/** Section 13. Last on the page and the only card with the danger border. */
export default function DeleteProjectSection({
  projectName,
  confirmName,
  onConfirmNameChange,
  onDelete,
  deleting,
  disabled,
  message,
}: DeleteProjectSectionProps) {
  const { t } = useTranslation();
  const confirmId = useId();
  const blocked =
    disabled || deleting || !projectName.trim() || confirmName.trim() !== projectName.trim();

  return (
    <SettingsSection
      variant="wsec"
      id="delete-project"
      tone="danger"
      title={t("signalProjectSettings.deleteProject.heading")}
      description={t("signalProjectSettings.deleteProject.description")}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="mb-0 min-w-[260px] flex-1">
          <label
            className="mb-2 block text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
            htmlFor={confirmId}
          >
            {t("signalProjectSettings.deleteProject.confirmLabel", { name: projectName })}
          </label>
          <input
            id={confirmId}
            className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
            type="text"
            placeholder={t("signalProjectSettings.deleteProject.confirmPlaceholder")}
            value={confirmName}
            onChange={(event) => onConfirmNameChange(event.target.value)}
            disabled={disabled || deleting}
          />
        </div>
        <button
          type="button"
          className="inline-flex h-[38px] flex-none cursor-pointer items-center gap-2 rounded-[10px] border border-[color-mix(in_srgb,var(--bad)_40%,transparent)] bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--bad) max-md:min-h-11"
          onClick={onDelete}
          disabled={blocked}
        >
          {deleting
            ? t("signalProjectSettings.deleteProject.buttonBusy")
            : t("signalProjectSettings.deleteProject.button")}
        </button>
      </div>

      <p className="mt-3.5 text-[12px] text-(--t-3)" role="status" aria-live="polite">
        {message}
      </p>
    </SettingsSection>
  );
}
