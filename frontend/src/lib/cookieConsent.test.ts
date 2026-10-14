import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  COOKIE_CONSENT_COOKIE_NAME,
  COOKIE_CONSENT_STORAGE_KEY,
  clearStoredConsentRecord,
  createConsentRecord,
  hasCategoryConsent,
  persistConsentRecord,
  readStoredConsentRecord,
  updateConsentRecord,
} from "@/lib/cookieConsent";

const clearConsentCookie = () => {
  document.cookie = `${COOKIE_CONSENT_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
};

describe("cookieConsent", () => {
  beforeEach(() => {
    window.localStorage.clear();
    clearConsentCookie();
    vi.useRealTimers();
  });

  it("creates consent records with strictly necessary cookies always enabled", () => {
    const record = createConsentRecord("save-preferences", {
      preferences: true,
      analytics: false,
      marketing: true,
    });

    expect(record.preferences.necessary).toBe(true);
    expect(record.preferences.preferences).toBe(true);
    expect(record.preferences.marketing).toBe(true);
  });

  it("never grants an optional category the caller omitted", () => {
    // normalizePreferences fills omitted categories from defaultCookieConsentPreferences, so
    // a non-false default would hand out consent nobody gave.
    const noneGiven = createConsentRecord("reject-optional");
    expect(hasCategoryConsent(noneGiven, "analytics")).toBe(false);
    expect(hasCategoryConsent(noneGiven, "marketing")).toBe(false);
    expect(hasCategoryConsent(noneGiven, "preferences")).toBe(false);

    // A partial save must not grant the categories it does not mention.
    const partialSave = updateConsentRecord(null, "save-preferences", { marketing: true });
    expect(hasCategoryConsent(partialSave, "marketing")).toBe(true);
    expect(hasCategoryConsent(partialSave, "analytics")).toBe(false);
    expect(hasCategoryConsent(partialSave, "preferences")).toBe(false);
    expect(partialSave.preferences.necessary).toBe(true);
  });

  it("persists records and restores valid payloads from localStorage", () => {
    const record = createConsentRecord("accept-all", {
      preferences: true,
      analytics: true,
      marketing: true,
    });

    persistConsentRecord(record);
    const restored = readStoredConsentRecord();

    expect(restored).toEqual(record);
    expect(document.cookie).toContain(`${COOKIE_CONSENT_COOKIE_NAME}=`);
  });

  it("returns null for malformed stored payloads", () => {
    window.localStorage.setItem(COOKIE_CONSENT_STORAGE_KEY, JSON.stringify({ version: 99 }));
    expect(readStoredConsentRecord()).toBeNull();
  });

  it("updates existing consent while preserving first consent timestamp", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-02-10T08:00:00.000Z"));
    const initialRecord = createConsentRecord("reject-optional");

    vi.setSystemTime(new Date("2026-02-10T09:30:00.000Z"));
    const updatedRecord = updateConsentRecord(initialRecord, "save-preferences", {
      analytics: true,
      marketing: false,
      preferences: true,
    });

    expect(updatedRecord.consentedAt).toBe(initialRecord.consentedAt);
    expect(updatedRecord.lastUpdatedAt).not.toBe(initialRecord.lastUpdatedAt);
    expect(hasCategoryConsent(updatedRecord, "analytics")).toBe(true);
    expect(updatedRecord.preferences.necessary).toBe(true);
  });

  it("clears stored consent in localStorage and cookie", () => {
    const record = createConsentRecord("accept-all", {
      preferences: true,
      analytics: true,
      marketing: true,
    });

    persistConsentRecord(record);
    clearStoredConsentRecord();

    expect(readStoredConsentRecord()).toBeNull();
    expect(document.cookie).not.toContain(`${COOKIE_CONSENT_COOKIE_NAME}=v`);
  });
});
