import { NextRequest, NextResponse } from "next/server";

import { isUsableToken } from "@/lib/auth-session";

import { buildAuthUrl, clearAuthCookies } from "../_route-utils";

export async function POST(request: NextRequest) {
  const token = request.cookies.get("auth_token")?.value;
  const refreshToken = request.cookies.get("auth_refresh_token")?.value;

  if (isUsableToken(token) || isUsableToken(refreshToken)) {
    try {
      const headers = new Headers({
        "Content-Type": "application/json",
      });
      if (isUsableToken(token)) {
        headers.set("Authorization", `Bearer ${token}`);
      }

      await fetch(buildAuthUrl("/auth/logout"), {
        method: "POST",
        headers,
        body: JSON.stringify(isUsableToken(refreshToken) ? { refresh_token: refreshToken } : {}),
        redirect: "manual",
      });
    } catch {
      // We still clear cookies even if the upstream is unreachable.
    }
  }

  const response = NextResponse.json({ ok: true });
  clearAuthCookies(response);
  return response;
}
