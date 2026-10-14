import { NextRequest, NextResponse } from "next/server";
import { loadSanitizedStatusPayload, requireAdminToken } from "../utils";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const auth = await requireAdminToken(request);
  if ("response" in auth) {
    return auth.response;
  }

  const result = await loadSanitizedStatusPayload(request, {
    path: "/system-status/admin",
    audience: "admin",
    token: auth.token,
  });

  if ("response" in result) {
    return result.response;
  }

  return NextResponse.json(result.payload);
}
