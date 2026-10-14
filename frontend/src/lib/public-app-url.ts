const FALLBACK_PUBLIC_APP_URL = "http://localhost:3000";

function normalizeBaseUrl(value: string | undefined): string {
  const normalized = (value || "").trim();
  if (!normalized) {
    return FALLBACK_PUBLIC_APP_URL;
  }
  return normalized.replace(/\/+$/, "");
}

export function resolvePublicAppUrl(): string {
  return normalizeBaseUrl(process.env.NEXT_PUBLIC_APP_URL || process.env.APP_BASE_URL);
}

export function toPublicUrl(path: string): string {
  const baseUrl = resolvePublicAppUrl();
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}
