"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  COOKIE_CONSENT_UPDATED_EVENT,
  type CookieConsentRecord,
  type OptionalCookieConsentCategory,
  createConsentRecord,
  hasCategoryConsent,
  persistConsentRecord,
  readStoredConsentRecord,
  updateConsentRecord,
} from "@/lib/cookieConsent";

type CookiePreferenceInput = Partial<Record<OptionalCookieConsentCategory, boolean>>;

type CookieConsentContextValue = {
  consentRecord: CookieConsentRecord | null;
  hasAnswered: boolean;
  isBannerVisible: boolean;
  isSettingsOpen: boolean;
  canUseCategory: (category: OptionalCookieConsentCategory) => boolean;
  openSettings: () => void;
  closeSettings: () => void;
  acceptAll: () => void;
  rejectOptional: () => void;
  savePreferences: (preferences: CookiePreferenceInput) => void;
};

const CookieConsentContext = createContext<CookieConsentContextValue | undefined>(undefined);

const emitConsentUpdatedEvent = (record: CookieConsentRecord) => {
  if (typeof window === "undefined") {
    return;
  }

  window.dispatchEvent(
    new CustomEvent(COOKIE_CONSENT_UPDATED_EVENT, {
      detail: record,
    })
  );
};

export function CookieConsentProvider({ children }: { children: React.ReactNode }) {
  const [consentRecord, setConsentRecord] = useState<CookieConsentRecord | null>(null);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  useEffect(() => {
    setConsentRecord(readStoredConsentRecord());
    setIsHydrated(true);
  }, []);

  const persistAndPublish = useCallback((record: CookieConsentRecord) => {
    setConsentRecord(record);
    persistConsentRecord(record);
    emitConsentUpdatedEvent(record);
  }, []);

  const openSettings = useCallback(() => {
    setIsSettingsOpen(true);
  }, []);

  const closeSettings = useCallback(() => {
    setIsSettingsOpen(false);
  }, []);

  const acceptAll = useCallback(() => {
    persistAndPublish(
      createConsentRecord("accept-all", {
        preferences: true,
        analytics: true,
        marketing: true,
      })
    );
    closeSettings();
  }, [closeSettings, persistAndPublish]);

  const rejectOptional = useCallback(() => {
    persistAndPublish(
      createConsentRecord("reject-optional", {
        preferences: false,
        analytics: false,
        marketing: false,
      })
    );
    closeSettings();
  }, [closeSettings, persistAndPublish]);

  const savePreferences = useCallback(
    (preferences: CookiePreferenceInput) => {
      persistAndPublish(updateConsentRecord(consentRecord, "save-preferences", preferences));
      closeSettings();
    },
    [closeSettings, consentRecord, persistAndPublish]
  );

  const canUseCategory = useCallback(
    (category: OptionalCookieConsentCategory) => hasCategoryConsent(consentRecord, category),
    [consentRecord]
  );

  const value = useMemo<CookieConsentContextValue>(
    () => ({
      consentRecord,
      hasAnswered: Boolean(consentRecord),
      isBannerVisible: isHydrated && !consentRecord,
      isSettingsOpen,
      canUseCategory,
      openSettings,
      closeSettings,
      acceptAll,
      rejectOptional,
      savePreferences,
    }),
    [
      acceptAll,
      canUseCategory,
      closeSettings,
      consentRecord,
      isHydrated,
      isSettingsOpen,
      openSettings,
      rejectOptional,
      savePreferences,
    ]
  );

  return <CookieConsentContext.Provider value={value}>{children}</CookieConsentContext.Provider>;
}

export const useCookieConsent = () => {
  const context = useContext(CookieConsentContext);
  if (!context) {
    throw new Error("useCookieConsent must be used within CookieConsentProvider");
  }
  return context;
};
