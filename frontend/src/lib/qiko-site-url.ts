// Base URL of the shared Qiko marketing site (qiko-website-v2), which hosts Home/Labs/About and
// this app's own Signal marketing pages side by side with one nav/footer. Used to cross-link back
// to the sibling product from Signal's own marketing header/footer (SIGNAL-1009).
const FALLBACK_QIKO_SITE_URL = "https://qiko.ai";

function normalizeBaseUrl(value: string | undefined): string {
  const normalized = (value || "").trim();
  if (!normalized) {
    return FALLBACK_QIKO_SITE_URL;
  }
  return normalized.replace(/\/+$/, "");
}

export function resolveQikoSiteUrl(): string {
  return normalizeBaseUrl(process.env.NEXT_PUBLIC_QIKO_SITE_URL);
}
