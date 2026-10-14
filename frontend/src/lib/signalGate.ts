// ---------------------------------------------------------------------------
// Private preview gate (cookie-based).
//
// A single shared password (SIGNAL_GATE_PASSWORD, server-only env) locks the
// whole Signal platform during the pre-launch preview. Unlike HTTP Basic Auth
// at the proxy, a cookie gate plays nicely with the SPA: once the cookie is
// set, every same-origin request (navigations, fetch/XHR, SSE) carries it
// automatically, so there are no repeated native browser auth popups and no
// 401s breaking CORS preflight / streaming flows.
//
// The cookie stores a one-way SHA-256 token derived from the password, so the
// plaintext password is never written to the client and the cookie cannot be
// trivially forged. Setting SIGNAL_GATE_PASSWORD to empty/unset disables the
// gate entirely (clean public launch — no code change needed).
// ---------------------------------------------------------------------------

export const GATE_COOKIE = "signal_gate";
export const GATE_PATH = "/gate";

/** The configured shared preview password, or null when the gate is disabled. */
export function getGatePassword(): string | null {
  const pw = process.env.SIGNAL_GATE_PASSWORD;
  return pw && pw.trim() ? pw : null;
}

/** Deterministic, one-way token stored in the gate cookie. */
export async function computeGateToken(password: string): Promise<string> {
  const data = new TextEncoder().encode(`signal-gate:v1:${password}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
