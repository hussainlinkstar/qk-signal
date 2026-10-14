import { NextRequest, NextResponse } from "next/server";

import { applyAuthCookies, forwardAuthExchange } from "../_route-utils";
import {
  MOCK_DEMO_EMAIL,
  MOCK_DEMO_PASSWORD,
  buildMockPreviewJwt,
  isMockPreviewEnabled,
} from "@/lib/mockPreviewAuth";

async function readLoginCredentials(
  request: NextRequest
): Promise<{ username: string; password: string } | null> {
  const contentType = request.headers.get("content-type") ?? "";
  try {
    if (contentType.includes("application/x-www-form-urlencoded")) {
      const text = await request.text();
      const params = new URLSearchParams(text);
      return {
        username: (params.get("username") ?? params.get("email") ?? "").trim(),
        password: params.get("password") ?? "",
      };
    }
    if (contentType.includes("application/json")) {
      const body = (await request.json()) as { username?: string; email?: string; password?: string };
      return {
        username: String(body.username ?? body.email ?? "").trim(),
        password: String(body.password ?? ""),
      };
    }
  } catch {
    return null;
  }
  return null;
}

export async function POST(request: NextRequest) {
  if (!isMockPreviewEnabled()) {
    return forwardAuthExchange(request, "/auth/login");
  }

  const credentials = await readLoginCredentials(request);
  if (!credentials) {
    return NextResponse.json({ detail: "Invalid login payload" }, { status: 400 });
  }

  const emailOk = credentials.username.toLowerCase() === MOCK_DEMO_EMAIL;
  const passwordOk = credentials.password === MOCK_DEMO_PASSWORD;
  if (!emailOk || !passwordOk) {
    return NextResponse.json({ detail: "Incorrect email or password" }, { status: 401 });
  }

  const accessToken = buildMockPreviewJwt();
  const refreshToken = buildMockPreviewJwt({ type: "refresh", remember_me: true });
  const response = NextResponse.json({ authenticated: true });
  applyAuthCookies(response, accessToken, refreshToken);
  return response;
}
