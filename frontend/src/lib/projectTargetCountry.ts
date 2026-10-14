import { COUNTRIES } from "@/lib/countryData";

/**
 * The scan form's "Main market" is a free-text field ("Romania", "London, UK",
 * "United States", or empty). A project's `target_country` is an ISO 3166-1
 * alpha-2 code and the API rejects every other shape, so passing the market
 * value straight through made automatic project creation fail for almost every
 * launch, which is what stopped a scan from starting (SIGV2-1110).
 *
 * This resolves the free text to a code only when that can be done with
 * certainty, and returns null otherwise. "No single target market" is a valid
 * project state, so dropping a value we cannot resolve is always safer than
 * guessing one: a wrong country ends up in the audit prompt.
 */

const COUNTRY_CODES: ReadonlySet<string> = new Set(COUNTRIES.map((country) => country.code));

const normalizeSegment = (value: string): string =>
  value.replace(/\./g, "").replace(/\s+/g, " ").trim().toLowerCase();

const COUNTRY_NAME_TO_CODE: ReadonlyMap<string, string> = new Map(
  COUNTRIES.map((country) => [normalizeSegment(country.name), country.code])
);

// Everyday names the country list does not carry verbatim. "UK" is the one
// that matters most: it is what people type, and it is not an ISO code (GB is).
const MARKET_ALIASES: Readonly<Record<string, string>> = {
  america: "US",
  britain: "GB",
  england: "GB",
  "great britain": "GB",
  holland: "NL",
  "northern ireland": "GB",
  scotland: "GB",
  uae: "AE",
  uk: "GB",
  "united states of america": "US",
  usa: "US",
  wales: "GB",
};

const resolveSegment = (segment: string): string | null => {
  const normalized = normalizeSegment(segment);
  if (!normalized) return null;

  const asCode = normalized.toUpperCase();
  if (asCode.length === 2 && COUNTRY_CODES.has(asCode)) {
    return asCode;
  }

  return COUNTRY_NAME_TO_CODE.get(normalized) ?? MARKET_ALIASES[normalized] ?? null;
};

export function resolveProjectTargetCountry(market: string | null | undefined): string | null {
  const raw = String(market ?? "").trim();
  if (!raw) return null;

  const whole = resolveSegment(raw);
  if (whole) return whole;

  // "London, UK" and "Bucharest, Romania" put the country in the last segment.
  const segments = raw.split(",");
  if (segments.length > 1) {
    return resolveSegment(segments[segments.length - 1]);
  }

  return null;
}
