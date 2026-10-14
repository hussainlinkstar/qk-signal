/** Mock-preview demo auth (local stub + Vercel MOCK_PREVIEW). */

export const MOCK_DEMO_EMAIL = "demo@demo.com";
export const MOCK_DEMO_PASSWORD = "demo";

export function isMockPreviewEnabled(): boolean {
  return process.env.MOCK_PREVIEW === "1" || process.env.MOCK_PREVIEW === "true";
}

export function buildMockPreviewJwt(extra: Record<string, unknown> = {}): string {
  const header = Buffer.from(JSON.stringify({ alg: "HS256" })).toString("base64url");
  const payload = Buffer.from(
    JSON.stringify({
      sub: "1",
      exp: Math.floor(Date.now() / 1000) + 86400 * 7,
      type: "access",
      ...extra,
    })
  ).toString("base64url");
  return `${header}.${payload}.mock-preview`;
}

export function isMockPreviewToken(token?: string | null): boolean {
  return typeof token === "string" && token.endsWith(".mock-preview");
}

/** Shape aligned with stub-backend /auth/me + normalizeUserProfile. */
export const MOCK_PREVIEW_USER = {
  id: 1,
  email: MOCK_DEMO_EMAIL,
  name: "Demo User",
  is_staff: false,
  portal_only: false,
  subscription_plan: "plan_standard",
  role: "OWNER",
  email_verified: true,
  permissions: [] as string[],
};

export function isMockUserPath(path: string): boolean {
  const normalized = path.replace(/^\/api\/v1/, "").replace(/^\//, "");
  return (
    normalized === "auth/me" ||
    normalized === "users/me" ||
    normalized.startsWith("users/me?")
  );
}
