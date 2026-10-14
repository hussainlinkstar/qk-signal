/**
 * Passkey (WebAuthn / FIDO2) browser-side service.
 *
 * Wraps @simplewebauthn/browser helpers and calls the backend passkey
 * endpoints via the BFF proxy.
 */

import { startRegistration, startAuthentication } from "@simplewebauthn/browser";
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PasskeyListItem {
  id: number;
  credential_id: string;
  name: string;
  created_at: string | null;
  last_used_at: string | null;
  backed_up: boolean;
}

export interface PasskeyRegistrationResult {
  id: number;
  credential_id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.message ?? detail;
    } catch {
      /* empty */
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

// ---------------------------------------------------------------------------
// Registration (authenticated)
// ---------------------------------------------------------------------------

export async function registerPasskey(
  token: string,
  name = "My Passkey"
): Promise<PasskeyRegistrationResult> {
  // 1. Get registration options from backend
  const { options } = await jsonFetch<{
    options: PublicKeyCredentialCreationOptionsJSON;
  }>("/api/auth/passkeys/register/generate-options", {
    headers: authHeaders(token),
  });

  // 2. Invoke browser WebAuthn prompt
  const credential = await startRegistration({ optionsJSON: options });

  // 3. Send attestation back to backend
  return jsonFetch<PasskeyRegistrationResult>("/api/auth/passkeys/register/verify", {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ credential, name }),
  });
}

// ---------------------------------------------------------------------------
// Authentication (public)
// ---------------------------------------------------------------------------

export async function checkHasPasskeys(email: string): Promise<boolean> {
  try {
    const { has_passkeys } = await jsonFetch<{ has_passkeys: boolean }>(
      `/api/auth/passkeys/has-credentials?email=${encodeURIComponent(email)}`
    );
    return has_passkeys;
  } catch {
    return false;
  }
}

export interface PasskeyLoginResult {
  authenticated: boolean;
}

export async function loginWithPasskey(email?: string): Promise<PasskeyLoginResult> {
  // 1. Get authentication options
  const qs = email ? `?email=${encodeURIComponent(email)}` : "";
  const { options } = await jsonFetch<{
    options: PublicKeyCredentialRequestOptionsJSON & { _challenge_hint?: string };
  }>(`/api/auth/passkeys/login/generate-options${qs}`);

  const challengeHint = options._challenge_hint;

  // 2. Invoke browser WebAuthn prompt
  const credential = await startAuthentication({ optionsJSON: options });

  // 3. Send assertion back, include challenge hint for lookup
  const body: Record<string, unknown> = { ...credential };
  if (challengeHint) {
    body._challenge_hint = challengeHint;
  }

  return jsonFetch<PasskeyLoginResult>("/api/auth/passkeys/login/verify", {
    method: "POST",
    body: JSON.stringify({ credential: body }),
  });
}

// ---------------------------------------------------------------------------
// Management (authenticated)
// ---------------------------------------------------------------------------

export async function listPasskeys(token: string): Promise<PasskeyListItem[]> {
  return jsonFetch<PasskeyListItem[]>("/api/auth/passkeys/list", {
    headers: authHeaders(token),
  });
}

export async function renamePasskey(
  token: string,
  passkeyId: number,
  name: string
): Promise<PasskeyListItem> {
  return jsonFetch<PasskeyListItem>(`/api/auth/passkeys/${passkeyId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ name }),
  });
}

export async function deletePasskey(token: string, passkeyId: number): Promise<void> {
  await jsonFetch<{ deleted: boolean }>(`/api/auth/passkeys/${passkeyId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}
