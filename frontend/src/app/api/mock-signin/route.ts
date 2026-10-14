import { NextResponse } from "next/server";

import { applyAuthCookies } from "@/app/api/auth/_route-utils";
import {
  buildMockPreviewJwt,
  isMockPreviewEnabled,
} from "@/lib/mockPreviewAuth";

export async function POST() {
  if (!isMockPreviewEnabled()) {
    return NextResponse.json({ detail: "Mock preview disabled" }, { status: 404 });
  }

  const accessToken = buildMockPreviewJwt();
  const refreshToken = buildMockPreviewJwt({ type: "refresh", remember_me: true });
  const response = NextResponse.json({ authenticated: true, workspace_id: 1 });
  applyAuthCookies(response, accessToken, refreshToken);
  return response;
}
