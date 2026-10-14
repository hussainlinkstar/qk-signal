import { NextResponse } from "next/server";

function buildMockJwt(extra: Record<string, unknown> = {}): string {
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

function mockPreviewEnabled(): boolean {
  return process.env.MOCK_PREVIEW === "1" || process.env.MOCK_PREVIEW === "true";
}

export async function POST() {
  if (!mockPreviewEnabled()) {
    return NextResponse.json({ detail: "Mock preview disabled" }, { status: 404 });
  }

  const accessToken = buildMockJwt();
  const refreshToken = buildMockJwt({ type: "refresh", remember_me: true });
  const secure = process.env.NODE_ENV === "production";
  const response = NextResponse.json({ authenticated: true, workspace_id: 1 });
  response.cookies.set("auth_token", accessToken, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure,
    maxAge: 86400 * 7,
  });
  response.cookies.set("auth_refresh_token", refreshToken, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure,
    maxAge: 86400 * 7,
  });
  return response;
}
