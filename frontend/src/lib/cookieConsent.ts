export const COOKIE_CONSENT_STORAGE_KEY = "geo-aeo-audit-tool.cookie-consent";
export const COOKIE_CONSENT_COOKIE_NAME = "geo_aeo_cookie_consent";
export const COOKIE_CONSENT_VERSION = 1;
export const COOKIE_CONSENT_UPDATED_EVENT = "geo-aeo-audit-tool:cookie-consent-updated";
export const COOKIE_CONSENT_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

export const cookieConsentCategories = [
  "necessary",
  "preferences",
  "analytics",
  "marketing",
] as const;

export type CookieConsentCategory = (typeof cookieConsentCategories)[number];
export type OptionalCookieConsentCategory = Exclude<CookieConsentCategory, "necessary">;
export type CookieConsentSource = "accept-all" | "reject-optional" | "save-preferences";

export type CookieConsentPreferences = Record<CookieConsentCategory, boolean>;

export type CookieConsentRecord = {
  version: number;
  source: CookieConsentSource;
  consentedAt: string;
  lastUpdatedAt: string;
  preferences: CookieConsentPreferences;
};

export const optionalCookieConsentCategories: OptionalCookieConsentCategory[] = [
  "preferences",
  "analytics",
  "marketing",
];

// Every optional category defaults to false. `normalizePreferences` fills any category a
// caller omitted from these values, so a non-false default here silently grants consent that
// the visitor never gave: it pre-ticks the toggle in the settings modal, and it turns an
// omitted key in a partial `savePreferences` call into a granted one. Pre-ticked consent for
// a non-essential category is not consent.
export const defaultCookieConsentPreferences: Readonly<CookieConsentPreferences> = Object.freeze({
  necessary: true,
  preferences: false,
  analytics: false,
  marketing: false,
});

const consentSources: CookieConsentSource[] = ["accept-all", "reject-optional", "save-preferences"];

const normalizePreferences = (
  preferences?: Partial<Record<CookieConsentCategory, boolean>>
): CookieConsentPreferences => ({
  ...defaultCookieConsentPreferences,
  ...preferences,
  necessary: true,
});

const isValidConsentRecord = (value: unknown): value is CookieConsentRecord => {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<CookieConsentRecord>;
  if (candidate.version !== COOKIE_CONSENT_VERSION) {
    return false;
  }

  if (!candidate.source || !consentSources.includes(candidate.source as CookieConsentSource)) {
    return false;
  }

  if (typeof candidate.consentedAt !== "string" || typeof candidate.lastUpdatedAt !== "string") {
    return false;
  }

  if (!candidate.preferences || typeof candidate.preferences !== "object") {
    return false;
  }

  for (const category of cookieConsentCategories) {
    if (typeof candidate.preferences[category] !== "boolean") {
      return false;
    }
  }

  return candidate.preferences.necessary === true;
};

const createTimestamp = () => new Date().toISOString();

const serializeConsentCookie = (preferences: CookieConsentPreferences) => {
  const preferenceFlag = preferences.preferences ? 1 : 0;
  const analyticsFlag = preferences.analytics ? 1 : 0;
  const marketingFlag = preferences.marketing ? 1 : 0;
  return `v${COOKIE_CONSENT_VERSION}.p${preferenceFlag}a${analyticsFlag}m${marketingFlag}`;
};

const writeConsentCookie = (record: CookieConsentRecord) => {
  if (typeof document === "undefined") {
    return;
  }

  const cookieSegments = [
    `${COOKIE_CONSENT_COOKIE_NAME}=${encodeURIComponent(serializeConsentCookie(record.preferences))}`,
    "Path=/",
    `Max-Age=${COOKIE_CONSENT_COOKIE_MAX_AGE_SECONDS}`,
    "SameSite=Lax",
  ];

  if (typeof window !== "undefined" && window.location.protocol === "https:") {
    cookieSegments.push("Secure");
  }

  document.cookie = cookieSegments.join("; ");
};

export const createConsentRecord = (
  source: CookieConsentSource,
  preferences?: Partial<Record<OptionalCookieConsentCategory, boolean>>
): CookieConsentRecord => {
  const timestamp = createTimestamp();
  return {
    version: COOKIE_CONSENT_VERSION,
    source,
    consentedAt: timestamp,
    lastUpdatedAt: timestamp,
    preferences: normalizePreferences(preferences),
  };
};

export const updateConsentRecord = (
  currentRecord: CookieConsentRecord | null,
  source: CookieConsentSource,
  preferences: Partial<Record<OptionalCookieConsentCategory, boolean>>
): CookieConsentRecord => {
  const timestamp = createTimestamp();
  const consentedAt = currentRecord?.consentedAt ?? timestamp;

  return {
    version: COOKIE_CONSENT_VERSION,
    source,
    consentedAt,
    lastUpdatedAt: timestamp,
    preferences: normalizePreferences({
      ...currentRecord?.preferences,
      ...preferences,
    }),
  };
};

export const readStoredConsentRecord = (): CookieConsentRecord | null => {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const rawValue = window.localStorage.getItem(COOKIE_CONSENT_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }

    const parsedValue: unknown = JSON.parse(rawValue);
    return isValidConsentRecord(parsedValue) ? parsedValue : null;
  } catch {
    return null;
  }
};

export const persistConsentRecord = (record: CookieConsentRecord) => {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(COOKIE_CONSENT_STORAGE_KEY, JSON.stringify(record));
  } catch {
    // Ignore storage write failures (private mode, quota, etc.).
  }

  writeConsentCookie(record);
};

export const clearStoredConsentRecord = () => {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.removeItem(COOKIE_CONSENT_STORAGE_KEY);
  } catch {
    // Ignore storage write failures.
  }

  if (typeof document !== "undefined") {
    document.cookie = `${COOKIE_CONSENT_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
  }
};

export const hasCategoryConsent = (
  record: CookieConsentRecord | null,
  category: OptionalCookieConsentCategory
) => Boolean(record?.preferences[category]);
