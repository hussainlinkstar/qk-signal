"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { TARGET_MARKET_OPTIONS } from "@/lib/targetMarket";

/**
 * Single source for the project-creation fields, used by both the workspace
 * overview's Add Project modal and the onboarding wizard. signal-MVP renders
 * the same four fields in two containers: the modal wraps every control in
 * `.minp` (boxed input with a leading icon), while the wizard uses `.wselect`
 * / `.winput` (standalone selects and inputs). `variant` picks the container;
 * the field set, labels and option lists are shared so the two surfaces can
 * never drift apart.
 *
 * Reporting language is deliberately English + Arabic only: those are the two
 * languages the product produces reports in. The approved Add Project modal
 * also offered Spanish/French/German, a recorded mockup inconsistency -
 * offering them would promise reports the backend cannot generate.
 */

export type ProjectFormFieldKey = "name" | "domain" | "market" | "language";

export type ProjectFormValues = {
  name: string;
  domain: string;
  market: string;
  language: string;
};

type Variant = "modal" | "wizard";

const FIELD_LABEL_CLASS =
  "mb-2 block font-(family-name:--font-roboto-mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";

// `.minp`: h-11 (44px) boxed input row on --paper with a 16px leading icon.
// The shell, not the bare field, carries the focus treatment: signal.css
// `.minp:focus-within` lights the whole pill (--panel ground, #C9CEF7 border,
// 3px --ring). `input-shell` is the opt-in hook for the matching rules in
// globals.css, which suppress the @tailwindcss/forms blue ring on the field
// inside and the forms chevron on a select that draws its own `.mchev`.
const MINP_CLASS =
  "input-shell group/minp flex h-11 items-center gap-[9px] rounded-[14px] border border-(--line) bg-white px-3 transition-colors focus-within:border-(--purple) focus-within:bg-white focus-within:shadow-[0_0_0_3px_rgba(147,51,234,0.12)]";
// signal.css `.minp:focus-within > svg`: the shell's icons, the `.mchev`
// indicator included, take the brand colour with the shell.
const MINP_ICON_CLASS =
  "h-4 w-4 flex-none text-(--t-3) transition-colors group-focus-within/minp:text-(--brand) [stroke-width:2]";
const MINP_CONTROL_CLASS =
  "min-w-0 flex-1 border-none bg-transparent py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3)";
const MINP_SELECT_CLASS = `${MINP_CONTROL_CLASS} cursor-pointer appearance-none`;

// `.wselect`: standalone bordered select; `wselect-chevron` supplies the
// chevron and `field-focus-ring` the approved keyboard-only ring.
const WSELECT_CLASS =
  "wselect-chevron field-focus-ring h-11 w-full cursor-pointer appearance-none rounded-[14px] border border-(--line) bg-white py-0 pl-[13px] pr-[34px] font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none disabled:opacity-60";

const ActivityIcon = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    aria-hidden="true"
    className={MINP_ICON_CLASS}
  >
    <path d="M4 12h4l2 5 4-13 2 8h4" />
  </svg>
);

const GlobeIcon = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    aria-hidden="true"
    className={MINP_ICON_CLASS}
  >
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" />
  </svg>
);

const SearchIcon = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    aria-hidden="true"
    className={MINP_ICON_CLASS}
  >
    <circle cx="11" cy="11" r="7" />
    <path d="M21 21l-4.3-4.3" />
  </svg>
);

const ChevronIcon = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    aria-hidden="true"
    className={`pointer-events-none ${MINP_ICON_CLASS}`}
  >
    <path d="M6 9l6 6 6-6" />
  </svg>
);

function FieldShell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      {children}
    </label>
  );
}

function Minp({
  icon,
  invalid,
  children,
}: {
  icon?: React.ReactNode;
  invalid?: boolean;
  children: React.ReactNode;
}) {
  // SIGV2-1294: a click anywhere in the shell reaches the control.
  //
  // The shell is a flex row, so the chevron takes its own column and the
  // select stops short of it. The chevron is `pointer-events-none`, so a
  // click on it fell through to this span and nothing happened: the one part
  // of the control that looks like a dropdown affordance was dead, while
  // clicking the text worked.
  //
  // The approved anatomy is not negotiable here. SIGV2-1201 pins the select
  // to `background-image: none` and `padding-inline-end: 0`, so widening it
  // under the chevron is not available, and overlaying the chevron would need
  // that padding back. Forwarding the click keeps the geometry and fixes the
  // affordance.
  const forwardToControl = (event: React.MouseEvent<HTMLSpanElement>) => {
    if (event.target !== event.currentTarget) return;
    const control = event.currentTarget.querySelector<HTMLElement>("select, input");
    if (!control || (control as HTMLSelectElement | HTMLInputElement).disabled) return;
    control.focus();
    // Chromium and Safari can open a native picker directly. Elsewhere focus
    // alone is the honest outcome: the control is ready for the keyboard.
    const picker = (control as HTMLSelectElement & { showPicker?: () => void }).showPicker;
    if (control instanceof HTMLSelectElement && typeof picker === "function") {
      try {
        picker.call(control);
      } catch {
        // Browsers refuse showPicker outside a user gesture they recognise.
        // Focus has already happened, so there is nothing to recover.
      }
    }
  };

  return (
    <span
      className={`${MINP_CLASS} ${invalid ? "border-(--bad)" : ""}`.trim()}
      onClick={forwardToControl}
    >
      {icon}
      {children}
    </span>
  );
}

export default function ProjectFormFields({
  fields,
  values,
  onChange,
  disabled,
  variant = "modal",
  domainInvalid,
}: {
  fields: ProjectFormFieldKey[];
  values: ProjectFormValues;
  onChange: (key: ProjectFormFieldKey, value: string) => void;
  disabled?: boolean;
  variant?: Variant;
  /** Wizard step 1 paints the domain border red on failed validation. */
  domainInvalid?: boolean;
}) {
  const { t } = useTranslation();

  const languageOptions = (
    <>
      <option value="en">{t("projectForm.languageEnglish")}</option>
      <option value="ar">{t("projectForm.languageArabic")}</option>
    </>
  );

  const marketOptions = TARGET_MARKET_OPTIONS.map((option) => (
    <option key={option.code} value={option.code}>
      {option.name}
    </option>
  ));

  const renderField = (field: ProjectFormFieldKey) => {
    switch (field) {
      case "name":
        return (
          <FieldShell key={field} label={t("projectForm.projectName")}>
            <Minp icon={ActivityIcon}>
              <input
                type="text"
                className={MINP_CONTROL_CLASS}
                placeholder={t("projectForm.projectNamePlaceholder")}
                value={values.name}
                disabled={disabled}
                onChange={(event) => onChange("name", event.target.value)}
              />
            </Minp>
          </FieldShell>
        );
      case "domain": {
        const domainControl = (
          <input
            type="text"
            className={MINP_CONTROL_CLASS}
            placeholder={t(
              variant === "wizard"
                ? "projectForm.domainPlaceholderWizard"
                : "projectForm.domainPlaceholder"
            )}
            value={values.domain}
            disabled={disabled}
            onChange={(event) => onChange("domain", event.target.value)}
          />
        );
        return (
          <FieldShell
            key={field}
            label={t(variant === "wizard" ? "projectForm.domain" : "projectForm.primaryDomain")}
          >
            <Minp icon={GlobeIcon} invalid={domainInvalid}>
              {domainControl}
            </Minp>
          </FieldShell>
        );
      }
      case "market":
        return (
          <FieldShell key={field} label={t("projectForm.targetMarket")}>
            {variant === "wizard" ? (
              <select
                className={WSELECT_CLASS}
                value={values.market}
                disabled={disabled}
                onChange={(event) => onChange("market", event.target.value)}
              >
                {marketOptions}
              </select>
            ) : (
              <Minp icon={SearchIcon}>
                <select
                  className={MINP_SELECT_CLASS}
                  value={values.market}
                  disabled={disabled}
                  onChange={(event) => onChange("market", event.target.value)}
                >
                  {marketOptions}
                </select>
                {ChevronIcon}
              </Minp>
            )}
          </FieldShell>
        );
      case "language":
        return (
          <FieldShell key={field} label={t("projectForm.reportingLanguage")}>
            {variant === "wizard" ? (
              <select
                className={WSELECT_CLASS}
                value={values.language}
                disabled={disabled}
                onChange={(event) => onChange("language", event.target.value)}
              >
                {languageOptions}
              </select>
            ) : (
              <Minp>
                <select
                  className={MINP_SELECT_CLASS}
                  value={values.language}
                  disabled={disabled}
                  onChange={(event) => onChange("language", event.target.value)}
                >
                  {languageOptions}
                </select>
                {ChevronIcon}
              </Minp>
            )}
          </FieldShell>
        );
    }
  };

  return <>{fields.map(renderField)}</>;
}
