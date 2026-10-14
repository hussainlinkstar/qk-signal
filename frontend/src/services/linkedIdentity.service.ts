/**
 * Linked sign-in identities (SIGV2-1257).
 *
 * Connecting Microsoft to an existing email/password account is proven with
 * that account's own password, from account settings. The provider leg is
 * started only after the backend accepts the password, and it is a full
 * browser navigation, so the caller hands the returned link token to
 * `resolveBackendAuthUrl`.
 */

export interface LinkedIdentityStatus {
  provider: string;
  configured: boolean;
  linked: boolean;
  linked_at: string | null;
}

export interface IdentityLinkStart {
  link_token: string;
  authorize_path: string;
}

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
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }

  return res.json() as Promise<T>;
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export async function listLinkedIdentities(token: string): Promise<LinkedIdentityStatus[]> {
  const { identities } = await jsonFetch<{ identities: LinkedIdentityStatus[] }>(
    "/api/auth/linked-identities",
    { headers: authHeaders(token) }
  );
  return identities ?? [];
}

export async function startIdentityLink(
  token: string,
  provider: string,
  currentPassword: string
): Promise<IdentityLinkStart> {
  return jsonFetch<IdentityLinkStart>(`/api/auth/linked-identities/${provider}/start`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ current_password: currentPassword, confirm: true }),
  });
}
