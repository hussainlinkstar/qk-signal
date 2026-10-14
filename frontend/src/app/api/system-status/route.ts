import { NextRequest, NextResponse } from "next/server";
import { loadSanitizedStatusPayload } from "./utils";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const result = await loadSanitizedStatusPayload(request, {
    path: "/system-status",
    audience: "public",
  });

  if ("response" in result) {
    return result.response;
  }

  return NextResponse.json(result.payload);
}
