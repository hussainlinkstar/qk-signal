import { NextRequest, NextResponse } from "next/server";
import { issueChallenge } from "../hmac";

export const runtime = "nodejs";

function resolveClientIp(request: NextRequest): string {
  return (
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-real-ip") ||
    "unknown"
  );
}

export async function GET(request: NextRequest) {
  const ip = resolveClientIp(request);
  const token = issueChallenge(ip);
  return NextResponse.json(
    { token },
    {
      headers: {
        "Cache-Control": "no-store, no-cache, must-revalidate",
      },
    }
  );
}
