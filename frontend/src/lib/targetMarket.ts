import { COUNTRIES, type CountryEntry } from "./countryData";

export const GLOBAL_TARGET_MARKET = "GLOBAL";

export const TARGET_MARKET_OPTIONS: CountryEntry[] = [
  { code: GLOBAL_TARGET_MARKET, name: "Global" },
  ...COUNTRIES,
];

export function toTargetCountry(value: string): string | null {
  const code = value.trim().toUpperCase();
  if (!code || code === GLOBAL_TARGET_MARKET) {
    return null;
  }
  return code;
}
