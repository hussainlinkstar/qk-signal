import { NextRequest, NextResponse } from "next/server";

import { applyAuthCookies, clearAuthCookies, refreshSessionFromCookie } from "../_route-utils";
import { isTokenExpired, isUsableToken, shouldRefreshToken } from "@/lib/auth-session";

const ENSURE_QUERY_PARAM = "ensure";

export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("auth_token")?.value ?? null;
  const refreshToken = request.cookies.get("auth_refresh_token")?.value ?? null;
  const ensureSession = request.nextUrl.searchParams.get(ENSURE_QUERY_PARAM) === "1";

  if (ensureSession) {
    if (
      isUsableToken(accessToken) &&
      !isTokenExpired(accessToken) &&
      !shouldRefreshToken(accessToken)
    ) {
      return NextResponse.json({ authenticated: true });
    }

    if (isUsableToken(refreshToken)) {
      return refreshSessionFromCookie(refreshToken);
    }

    const response = NextResponse.json({ authenticated: false });
    if (isUsableToken(accessToken)) {
      clearAuthCookies(response);
    }
    return response;
  }

  return NextResponse.json({
    authenticated: isUsableToken(accessToken) || isUsableToken(refreshToken),
  });
}

export async function POST(request: NextRequest) {
  const payload = (await request.json().catch(() => null)) as {
    access_token?: string;
    refresh_token?: string;
  } | null;

  const accessToken = payload?.access_token;
  const refreshToken = payload?.refresh_token;

  if (!isUsableToken(accessToken) || !isUsableToken(refreshToken)) {
    return NextResponse.json({ detail: "Invalid auth session payload" }, { status: 400 });
  }

  const response = NextResponse.json({ authenticated: true });
  applyAuthCookies(response, accessToken, refreshToken);
  return response;
}
