"use client";

import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";
import { Settings2, ShieldCheck, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import { cx } from "@/components/ui/utils";
import { useCookieConsent } from "@/contexts/CookieConsentContext";
import { resolveQikoSiteUrl } from "@/lib/qiko-site-url";
import {
  defaultCookieConsentPreferences,
  type CookieConsentRecord,
  type OptionalCookieConsentCategory,
  optionalCookieConsentCategories,
} from "@/lib/cookieConsent";

type DraftOptionalPreferences = Record<OptionalCookieConsentCategory, boolean>;

type PreferenceRowProps = {
  title: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  badge?: string;
  onToggle?: () => void;
};

const buildDraftPreferences = (record: CookieConsentRecord | null): DraftOptionalPreferences => ({
  preferences: record?.preferences.preferences ?? defaultCookieConsentPreferences.preferences,
  analytics: record?.preferences.analytics ?? defaultCookieConsentPreferences.analytics,
  marketing: record?.preferences.marketing ?? defaultCookieConsentPreferences.marketing,
});

const PreferenceSwitch = ({
  label,
  checked,
  disabled = false,
  onToggle,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onToggle?: () => void;
}) => (
  <button
    type="button"
    role="switch"
    aria-label={label}
    aria-checked={checked}
    disabled={disabled}
    onClick={onToggle}
    className={cx(
      "relative h-6 w-[42px] shrink-0 cursor-pointer rounded-full border-none focus-visible:outline-hidden focus-visible:ring-[3px] focus-visible:ring-(--ring) disabled:cursor-default disabled:opacity-55",
      checked ? "bg-(--good)" : "bg-(--line)"
    )}
  >
    <span
      className={cx(
        "absolute start-[3px] top-[3px] h-[18px] w-[18px] rounded-full bg-(--panel) transition-transform duration-200 motion-reduce:transition-none",
        checked ? "translate-x-[18px] rtl:-translate-x-[18px]" : "translate-x-0"
      )}
    />
  </button>
);

const PreferenceRow = ({
  title,
  description,
  checked,
  disabled = false,
  badge,
  onToggle,
}: PreferenceRowProps) => (
  <article className="flex items-center justify-between gap-3.5 rounded-[14px] border-0 bg-[#F7F8FA] px-3.5 py-3">
    <div>
      <p className="text-[13.5px] font-semibold text-(--t-1)">{title}</p>
      <p className="mt-[3px] text-[12px] leading-[1.45] text-(--t-3)">{description}</p>
      {badge ? (
        <span
          data-consent-label
          className="mt-2 inline-flex rounded-[5px] bg-(--good-s) px-[7px] py-0.5 font-mono text-[10.5px] text-(--good)"
        >
          {badge}
        </span>
      ) : null}
    </div>
    <PreferenceSwitch label={title} checked={checked} disabled={disabled} onToggle={onToggle} />
  </article>
);

export default function CookieConsentManager() {
  const { t } = useTranslation();
  const {
    consentRecord,
    isBannerVisible,
    isSettingsOpen,
    openSettings,
    closeSettings,
    acceptAll,
    rejectOptional,
    savePreferences,
  } = useCookieConsent();

  const [draftPreferences, setDraftPreferences] = useState<DraftOptionalPreferences>(() =>
    buildDraftPreferences(consentRecord)
  );

  const optionalCategoryConfig = useMemo(
    () => [
      {
        category: "preferences" as const,
        title: t("cookieConsent.categories.preferences.title"),
        description: t("cookieConsent.categories.preferences.description"),
      },
      {
        category: "analytics" as const,
        title: t("cookieConsent.categories.analytics.title"),
        description: t("cookieConsent.categories.analytics.description"),
      },
      {
        category: "marketing" as const,
        title: t("cookieConsent.categories.marketing.title"),
        description: t("cookieConsent.categories.marketing.description"),
      },
    ],
    [t]
  );

  useEffect(() => {
    if (!isSettingsOpen) return;
    setDraftPreferences(buildDraftPreferences(consentRecord));
  }, [consentRecord, isSettingsOpen]);

  const toggleCategory = (category: OptionalCookieConsentCategory) => {
    setDraftPreferences((current) => ({ ...current, [category]: !current[category] }));
  };

  const handleSavePreferences = () => savePreferences(draftPreferences);

  return (
    <div
      data-signal-theme
      className="contents font-(family-name:--body-font) leading-[normal] text-(--t-1)"
    >
      {isBannerVisible && !isSettingsOpen ? (
        <section
          aria-label={t("cookieConsent.banner.ariaLabel")}
          className="fixed inset-x-4 bottom-4 z-popover md:start-4 md:end-auto md:max-w-[560px]"
        >
          <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px] shadow-[0_8px_28px_var(--ink-s7)]">
            <p
              data-consent-label
              className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-(--t-3)"
            >
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
              {t("cookieConsent.banner.kicker")}
            </p>
            <h2 className="mt-2 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em]">
              {t("cookieConsent.banner.title")}
            </h2>
            <p className="mt-2 text-[13px] leading-[1.5] text-(--t-2)">
              {t("cookieConsent.banner.description")}{" "}
              <Link
                href={`${resolveQikoSiteUrl()}/signal/privacy`}
                className="font-medium text-(--blue) hover:underline"
              >
                {t("cookieConsent.banner.privacyLink")}
              </Link>
            </p>
            <div className="mt-3.5 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button size="sm" variant="outline" onClick={openSettings}>
                <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
                {t("cookieConsent.actions.managePreferences")}
              </Button>
              <Button size="sm" variant="outline" onClick={rejectOptional}>
                {t("cookieConsent.actions.rejectOptional")}
              </Button>
              <Button size="sm" variant="primary" onClick={acceptAll}>
                {t("cookieConsent.actions.acceptAll")}
              </Button>
            </div>
          </div>
        </section>
      ) : null}

      <Modal
        open={isSettingsOpen}
        onClose={closeSettings}
        title={t("cookieConsent.modal.ariaLabel")}
        ariaDescribedby="cookie-preferences-description"
        panelClassName="flex w-[460px] flex-col overflow-hidden"
      >
        <div className="shrink-0">
          <button
            type="button"
            onClick={closeSettings}
            className="absolute end-3 top-3 flex h-9 w-9 items-center justify-center rounded-(--r-sm) text-(--t-3) hover:bg-(--line-2) focus-visible:outline-hidden focus-visible:ring-[3px] focus-visible:ring-(--ring)"
            aria-label={t("cookieConsent.actions.close")}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
          <h2
            aria-hidden="true"
            className="pe-6 font-(family-name:--disp) text-[23px] font-extrabold tracking-[-0.02em]"
          >
            {t("cookieConsent.modal.title")}
          </h2>
          <p
            id="cookie-preferences-description"
            className="mt-1.5 text-[13.5px] leading-[1.5] text-(--t-2)"
          >
            {t("cookieConsent.modal.description")}
          </p>
        </div>

        <div className="mt-3.5 mb-1 flex min-h-0 flex-col gap-3 overflow-y-auto">
          <PreferenceRow
            title={t("cookieConsent.categories.necessary.title")}
            description={t("cookieConsent.categories.necessary.description")}
            checked
            disabled
            badge={t("cookieConsent.categories.necessary.alwaysOn")}
          />
          {optionalCookieConsentCategories.map((categoryKey) => {
            const config = optionalCategoryConfig.find((item) => item.category === categoryKey);
            if (!config) return null;
            return (
              <PreferenceRow
                key={categoryKey}
                title={config.title}
                description={config.description}
                checked={draftPreferences[categoryKey]}
                onToggle={() => toggleCategory(categoryKey)}
              />
            );
          })}
        </div>

        <footer className="mt-6 flex shrink-0 flex-col justify-end gap-2.5 sm:flex-row sm:flex-wrap">
          <Button variant="outline" onClick={rejectOptional}>
            {t("cookieConsent.actions.rejectOptional")}
          </Button>
          <Button variant="outline" onClick={acceptAll}>
            {t("cookieConsent.actions.acceptAll")}
          </Button>
          <Button variant="primary" onClick={handleSavePreferences}>
            {t("cookieConsent.actions.savePreferences")}
          </Button>
        </footer>
      </Modal>
    </div>
  );
}
