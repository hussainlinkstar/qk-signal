import {
  normalizeAuditReportWithDiagnostics,
  type NormalizeAuditReportWithDiagnosticsResult,
} from "@/lib/auditNormalization";
import { EU_AUDIT_LANGUAGES } from "@/constants/auditLanguages";
import type { AuditRecordResponse, EntityCandidate } from "@/types/auditWorkspace";

const CATEGORY_ALIAS_MAP: Record<string, string> = {
  saas: "SaaS - B2B Software Platform",
  software: "SaaS - B2B Software Platform",
  "software as a service": "SaaS - B2B Software Platform",
  ecommerce: "E-commerce - Online Retail Store",
  "e-commerce": "E-commerce - Online Retail Store",
  retail: "E-commerce - Online Retail Store",
  finance: "Finance - Financial Services",
  fintech: "Finance - Financial Services",
  health: "Healthcare - Medical Practice",
  healthcare: "Healthcare - Medical Practice",
  medical: "Healthcare - Medical Practice",
  travel: "Travel - Tourism & Hospitality",
  tourism: "Travel - Tourism & Hospitality",
  hospitality: "Travel - Tourism & Hospitality",
  media: "Media & Publishing",
  publishing: "Media & Publishing",
  blog: "Media & Publishing",
  news: "Media & Publishing",
  agency: "Agency - Marketing / Creative",
  technology: "Technology - Product Company",
  "tech company": "Technology - Product Company",
  "dental clinic": "Local Business - Dental Clinic",
  dentistry: "Local Business - Dental Clinic",
  dentist: "Local Business - Dental Clinic",
  "law firm": "Local Business - Law Firm",
  legal: "Local Business - Law Firm",
  lawyer: "Local Business - Law Firm",
  hvac: "Local Business - HVAC Services",
  "real estate": "Local Business - Real Estate Agency",
  realtor: "Local Business - Real Estate Agency",
  plumbing: "Local Business - Plumbing Services",
  roofing: "Local Business - Roofing Services",
  "event planner": "Local Business - Event Planner & Wedding Services",
  "wedding planner": "Local Business - Event Planner & Wedding Services",
  "event planning": "Local Business - Event Planner & Wedding Services",
  "wedding florist": "Local Business - Wedding Florist",
  florist: "Local Business - Wedding Florist",
  "flower shop": "Local Business - Wedding Florist",
  "local business": "Local Business - Service Provider",
  local: "Local Business - Service Provider",
  business: "General Business Website",
  general: "General Business Website",
  "general business website": "General Business Website",
};

const SUPPORTED_LANGUAGE_CODES = new Set(
  EU_AUDIT_LANGUAGES.map((option) => option.code.toLowerCase())
);

const LANGUAGE_ALIAS_MAP: Record<string, string> = {
  english: "en",
  "en-us": "en",
  "en-gb": "en",
  german: "de",
  deutsch: "de",
  french: "fr",
  spanish: "es",
  italian: "it",
  dutch: "nl",
  portuguese: "pt",
  polish: "pl",
  czech: "cs",
  swedish: "sv",
  danish: "da",
  finnish: "fi",
  greek: "el",
  hungarian: "hu",
  bulgarian: "bg",
  croatian: "hr",
  slovak: "sk",
  slovenian: "sl",
  lithuanian: "lt",
  latvian: "lv",
  estonian: "et",
  irish: "ga",
  maltese: "mt",
};

const MARKET_ALIAS_MAP: Record<string, string> = {
  global: "Global",
  worldwide: "Global",
  international: "Global",
  romania: "Romania",
  ro: "Romania",
  "united states": "United States",
  us: "United States",
  usa: "United States",
  "united kingdom": "United Kingdom",
  uk: "United Kingdom",
  england: "United Kingdom",
  germany: "Germany",
  france: "France",
  spain: "Spain",
  italy: "Italy",
  netherlands: "Netherlands",
  europe: "Europe",
  eu: "Europe",
};

const normalizeCategoryKey = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9/&+\-\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

const normalizeLanguageKey = (value: string) =>
  value
    .toLowerCase()
    .replace(/[_]/g, "-")
    .replace(/[^a-z\-\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

const deriveEventCategory = (signalText: string): string | null => {
  const hasWeddingIntent = /(wedding|nunt|mireas|bride|groom|ceremony|reception)/.test(signalText);
  const hasFloristIntent =
    /(florist|floral|flowers?|flower|bouquet|aranjament floral|flori|buchet)/.test(signalText);
  const hasEventPlanningIntent =
    /(event planner|events?\b|decor|decoration|styling|planning|organizare eveniment)/.test(
      signalText
    );

  if (hasEventPlanningIntent || hasWeddingIntent) {
    return "Local Business - Event Planner & Wedding Services";
  }
  if (hasFloristIntent) {
    return "Local Business - Wedding Florist";
  }

  return null;
};

const deriveLocalBusinessCategory = (signalText: string): string => {
  const eventCategory = deriveEventCategory(signalText);
  if (eventCategory) {
    return eventCategory;
  }

  if (/(dent|orthodont|clinic|stomatolog)/.test(signalText)) {
    return "Local Business - Dental Clinic";
  }
  if (/(law|attorney|legal|avocat)/.test(signalText)) {
    return "Local Business - Law Firm";
  }
  if (/(hvac|air.?condition|heating|cooling)/.test(signalText)) {
    return "Local Business - HVAC Services";
  }
  if (/(plumb|sewer|drain)/.test(signalText)) {
    return "Local Business - Plumbing Services";
  }
  if (/(roof|roofing)/.test(signalText)) {
    return "Local Business - Roofing Services";
  }
  if (/(real estate|realtor|property|imobil)/.test(signalText)) {
    return "Local Business - Real Estate Agency";
  }
  return "Local Business - Service Provider";
};

const extractHostTokens = (rawUrl: string): string[] => {
  const trimmed = rawUrl.trim();
  if (!trimmed) return [];

  try {
    const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    const hostname = new URL(candidate).hostname.replace(/^www\./i, "").toLowerCase();
    return hostname.split(/[.\-_]+/).filter(Boolean);
  } catch {
    return trimmed
      .toLowerCase()
      .replace(/^https?:\/\//i, "")
      .split(/[/?#.\-_]+/)
      .filter(Boolean);
  }
};

const looksLikeSaasHostname = (tokens: string[]): boolean => {
  const hasBrandAiSuffix = tokens.some((token) => token.length >= 8 && token.endsWith("ai"));
  if (hasBrandAiSuffix) return true;

  return tokens.some((token) =>
    /(^ai$|^ai|saas|app|cloud|platform|software|api|tech|labs|studio|automation|agent|bot|data)/.test(
      token
    )
  );
};

const normalizeLanguageCandidate = (value: string): string => {
  const normalized = normalizeLanguageKey(value);
  if (!normalized) return "";

  if (SUPPORTED_LANGUAGE_CODES.has(normalized)) {
    return normalized;
  }

  if (/^[a-z]{2}-[a-z]{2}$/.test(normalized)) {
    const base = normalized.slice(0, 2);
    if (SUPPORTED_LANGUAGE_CODES.has(base)) {
      return base;
    }
  }

  return LANGUAGE_ALIAS_MAP[normalized] ?? "";
};

export const normalizeDiscoveredLanguage = (
  rawLanguage: string,
  context?: { url?: string; category?: string }
): string => {
  void context;
  let language = normalizeLanguageCandidate(String(rawLanguage ?? ""));

  if (!language) {
    language = "en";
  }

  return language;
};

export const normalizeDiscoveredMarket = (
  rawMarket: string,
  context?: { url?: string; language?: string; category?: string }
): string => {
  void context;

  const marketCandidate = normalizeCategoryKey(String(rawMarket ?? ""));
  const market = MARKET_ALIAS_MAP[marketCandidate] ?? String(rawMarket ?? "").trim();

  return market;
};

export const normalizeDiscoveredCategory = (
  rawCategory: string,
  context?: { url?: string; entities?: EntityCandidate[] }
): string => {
  const trimmed = String(rawCategory ?? "").trim();
  if (!trimmed) return "";

  const normalized = normalizeCategoryKey(trimmed);
  if (!normalized) return "";

  const contextUrl = String(context?.url ?? "").toLowerCase();
  const hostTokens = extractHostTokens(contextUrl);
  const categorySignals = [
    normalized,
    contextUrl,
    ...hostTokens,
    ...(context?.entities ?? []).flatMap((entity) => [
      entity.name.toLowerCase(),
      String(entity.type ?? "").toLowerCase(),
    ]),
  ].join(" ");

  const looksLikeSaasContext =
    /(\bsaas\b|software|platform|api|cloud|artificial intelligence|automation|analytics|dashboard|agent|llm|model)/.test(
      categorySignals
    ) || looksLikeSaasHostname(hostTokens);
  const explicitEventCategory = deriveEventCategory(categorySignals);
  const looksLikeLocalServiceContext =
    /(dent|clinic|orthodont|law|attorney|legal|hvac|plumb|roof|realtor|real estate|service area|near me)/.test(
      categorySignals
    );

  if (
    explicitEventCategory &&
    (normalized.includes("agency") ||
      normalized.includes("event") ||
      normalized.includes("wedding") ||
      normalized.startsWith("local business") ||
      normalized === "business" ||
      normalized === "general" ||
      normalized === "general business website")
  ) {
    return explicitEventCategory;
  }

  if (
    (normalized.startsWith("local business") ||
      normalized === "business" ||
      normalized === "general" ||
      normalized === "general business website") &&
    looksLikeSaasContext &&
    !looksLikeLocalServiceContext
  ) {
    return "SaaS - B2B Software Platform";
  }

  const directMatch = CATEGORY_ALIAS_MAP[normalized];
  if (directMatch) {
    if (directMatch.startsWith("Local Business")) {
      return deriveLocalBusinessCategory(categorySignals);
    }
    return directMatch;
  }

  if (normalized.includes("saas") || normalized.includes("software")) {
    return "SaaS - B2B Software Platform";
  }
  if (
    normalized.includes("ecommerce") ||
    normalized.includes("e-commerce") ||
    normalized.includes("retail")
  ) {
    return "E-commerce - Online Retail Store";
  }
  if (normalized.includes("finance") || normalized.includes("fintech")) {
    return "Finance - Financial Services";
  }
  if (
    normalized.includes("health") ||
    normalized.includes("medical") ||
    normalized.includes("clinic")
  ) {
    return "Healthcare - Medical Practice";
  }
  if (
    normalized.includes("local") ||
    normalized.includes("service business") ||
    normalized.includes("location")
  ) {
    const categorySignals = [
      normalized,
      String(context?.url ?? "").toLowerCase(),
      ...(context?.entities ?? []).flatMap((entity) => [
        entity.name.toLowerCase(),
        String(entity.type ?? "").toLowerCase(),
      ]),
    ].join(" ");
    return deriveLocalBusinessCategory(categorySignals);
  }

  return trimmed;
};

export const normalizeReport = (payload: AuditRecordResponse, url: string) => {
  const normalized = normalizeReportWithDiagnostics(payload, url);
  if (!normalized.report) {
    throw new Error(normalized.diagnostics.summary);
  }
  return normalized.report;
};

export const normalizeReportWithDiagnostics = (
  payload: AuditRecordResponse,
  url: string
): NormalizeAuditReportWithDiagnosticsResult => {
  const rawReport: Record<string, any> = payload.full_report
    ? { ...payload.full_report }
    : { ...payload };
  const injectedPaths = new Set<string>();

  if (payload.full_report) {
    if (rawReport.scores?.geo == null && payload.geo_score != null) {
      injectedPaths.add("scores.geo");
    }
    if (rawReport.scores?.seo == null && payload.seo_score != null) {
      injectedPaths.add("scores.seo");
    }
    if (rawReport.scores?.aeo == null && payload.aeo_score != null) {
      injectedPaths.add("scores.aeo");
    }

    rawReport.scores = {
      ...rawReport.scores,
      geo: payload.geo_score ?? rawReport.scores?.geo,
      seo: payload.seo_score ?? rawReport.scores?.seo,
      aeo: payload.aeo_score ?? rawReport.scores?.aeo,
    };

    if (!rawReport.entity_analysis && payload.entity_analysis) {
      injectedPaths.add("entity_analysis");
    }
    if (!rawReport.aeo_signals && payload.aeo_signals) {
      injectedPaths.add("aeo_signals");
    }
    if (!rawReport.geo_signals && payload.geo_signals) {
      injectedPaths.add("geo_signals");
    }
    if (!rawReport.technical_signals && payload.technical_signals) {
      injectedPaths.add("technical_signals");
    }

    rawReport.entity_analysis = payload.entity_analysis ?? rawReport.entity_analysis;
    rawReport.aeo_signals = payload.aeo_signals ?? rawReport.aeo_signals;
    rawReport.geo_signals = payload.geo_signals ?? rawReport.geo_signals;
    rawReport.technical_signals = payload.technical_signals ?? rawReport.technical_signals;
  }

  const normalized = normalizeAuditReportWithDiagnostics(rawReport, { injectedPaths });
  return {
    ...normalized,
    report: normalized.report
      ? {
          ...normalized.report,
          url: normalized.report.url || url,
        }
      : null,
  };
};

export const formatISO = (input: string | Date): string => {
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return "-";
  return date.toISOString().slice(0, 10);
};

export const generateEntitySuggestions = (targetUrl: string): EntityCandidate[] => {
  const parsedUrl = new URL(targetUrl);
  const hostname = parsedUrl.hostname.replace(/^www\./i, "");
  const [brandChunk] = hostname.split(".");
  const normalizedBrand = brandChunk
    .split(/[-_]/)
    .filter(Boolean)
    .map((token) => token[0]?.toUpperCase() + token.slice(1))
    .join(" ");

  const fallbackBrand = normalizedBrand || "Your Brand";
  return [fallbackBrand, `${fallbackBrand} alternatives`, `${fallbackBrand} competitors`].map(
    (name) => ({ name, type: "Entity", confidence: null })
  );
};

export const inferCategoryFromEntities = (entities: EntityCandidate[]): string | null => {
  if (!entities.length) return null;

  const normalizedTypes = entities
    .map((entity) => entity.type?.toLowerCase().trim())
    .filter(Boolean) as string[];

  if (!normalizedTypes.length) return null;

  if (normalizedTypes.some((type) => type.includes("organization")))
    return "General Business Website";
  if (normalizedTypes.some((type) => type.includes("product")))
    return "E-commerce - Online Retail Store";
  if (normalizedTypes.some((type) => type.includes("location") || type.includes("gpe"))) {
    return "Local Business - Service Provider";
  }
  if (normalizedTypes.some((type) => type.includes("person")))
    return "Personal Brand / Expert Site";
  if (normalizedTypes.some((type) => type.includes("event"))) return "Events & Conferences";

  return null;
};

export const parseEntityTokens = (value: string) =>
  value
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);

export const hasMarketContent = (value: string) =>
  Array.from(value).some((character) => {
    if (/\d/.test(character)) return true;
    return character.toLowerCase() !== character.toUpperCase();
  });
