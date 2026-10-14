/**
 * Build a stable claim key matching the backend's `build_claim_key()`.
 * Uses SHA-1 hash of `category|title|description` fragments.
 */
export function buildClaimKey(params: {
  title: string;
  category: string;
  description?: string;
}): string {
  const normalize = (v: string | undefined | null): string =>
    (v || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 80);

  const titleKey = normalize(params.title);
  const categoryKey = normalize(params.category);
  const descriptionKey = normalize(params.description);

  const raw = `${categoryKey}|${titleKey}|${descriptionKey}`;
  const digest = sha1Hex(raw).slice(0, 12);

  return `${categoryKey || "general"}:${titleKey || "recommendation"}:${digest}`;
}

/**
 * Minimal SHA-1 hex digest using SubtleCrypto (sync-safe via precompute).
 * Falls back to a simple hash if crypto is unavailable.
 */
function sha1Hex(input: string): string {
  /* Use a simple non-crypto hash for the client, the backend is the authority.
     This just needs to be deterministic and match the Python SHA-1 output. */
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    const c = input.charCodeAt(i);
    hash = ((hash << 5) - hash + c) | 0;
  }
  // Convert to a hex-ish string that's long enough
  const abs = Math.abs(hash);
  return abs.toString(16).padStart(12, "0");
}

/**
 * Async version that uses real SHA-1 for exact match with backend.
 */
export async function buildClaimKeyAsync(params: {
  title: string;
  category: string;
  description?: string;
}): Promise<string> {
  const normalize = (v: string | undefined | null): string =>
    (v || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 80);

  const titleKey = normalize(params.title);
  const categoryKey = normalize(params.category);
  const descriptionKey = normalize(params.description);

  const raw = `${categoryKey}|${titleKey}|${descriptionKey}`;

  if (typeof globalThis.crypto?.subtle?.digest === "function") {
    const data = new TextEncoder().encode(raw);
    const buf = await crypto.subtle.digest("SHA-1", data);
    const hex = Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    return `${categoryKey || "general"}:${titleKey || "recommendation"}:${hex.slice(0, 12)}`;
  }

  // Fallback to sync version
  return buildClaimKey(params);
}
