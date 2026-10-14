export const COOKIE_SESSION_BEARER = "__cookie_session__";

const MALFORMED_TOKEN_VALUES = new Set(["", "undefined", "null"]);
const DEFAULT_CLOCK_SKEW_SECONDS = 60;
const DEFAULT_REFRESH_WINDOW_SECONDS = 300;

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");

  if (typeof atob === "function") {
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  return Buffer.from(padded, "base64").toString("utf8");
}

export function isUsableToken(value?: string | null): value is string {
  if (typeof value !== "string") {
    return false;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 && !MALFORMED_TOKEN_VALUES.has(trimmed);
}

export function isCookieSessionBearer(value?: string | null): boolean {
  return typeof value === "string" && value.trim() === COOKIE_SESSION_BEARER;
}

export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  if (!isUsableToken(token) || isCookieSessionBearer(token)) {
    return null;
  }

  const parts = token.split(".");
  if (parts.length < 2) {
    return null;
  }

  try {
    const payload = decodeBase64Url(parts[1]);
    return JSON.parse(payload) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function getTokenMaxAgeSeconds(token: string): number | undefined {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") {
    return undefined;
  }

  const now = Math.floor(Date.now() / 1000);
  const ttl = Math.max(0, Math.floor(exp - now));
  return ttl > 0 ? ttl : undefined;
}

export function shouldPersistCookies(refreshToken: string): boolean {
  const payload = decodeJwtPayload(refreshToken);
  return Boolean(payload?.remember_me);
}

export function isTokenExpired(
  token: string,
  clockSkewSeconds = DEFAULT_CLOCK_SKEW_SECONDS
): boolean {
  if (isCookieSessionBearer(token)) {
    return false;
  }

  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") {
    return true;
  }

  const nowWithSkew = Date.now() / 1000 + clockSkewSeconds;
  return exp < nowWithSkew;
}

export function shouldRefreshToken(
  token: string,
  clockSkewSeconds = DEFAULT_CLOCK_SKEW_SECONDS,
  refreshWindowSeconds = DEFAULT_REFRESH_WINDOW_SECONDS
): boolean {
  if (!isUsableToken(token) || isCookieSessionBearer(token)) {
    return false;
  }

  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") {
    return true;
  }

  const currentTime = Date.now() / 1000 + clockSkewSeconds;
  return exp - currentTime < refreshWindowSeconds;
}
