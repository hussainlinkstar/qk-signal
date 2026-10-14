import { NextRequest, NextResponse } from "next/server";
import { proxyRequest } from "../proxy";
import { verifyChallenge } from "./hmac";

export const runtime = "nodejs";
export const maxDuration = 120;

function resolveClientIp(request: NextRequest): string {
  return (
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-real-ip") ||
    "unknown"
  );
}

export async function POST(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = (await request.clone().json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ detail: "Invalid request body." }, { status: 400 });
  }

  const token = typeof body._challenge === "string" ? body._challenge : null;
  if (!token) {
    return NextResponse.json(
      { detail: "Missing challenge token. Please reload the page and try again." },
      { status: 403 }
    );
  }

  const ip = resolveClientIp(request);
  const result = verifyChallenge(token, ip);
  if (!result.ok) {
    const reason = "reason" in result ? result.reason : "unknown";
    console.warn("[guest-audit] challenge failed", { reason, ip });
    return NextResponse.json(
      { detail: "Challenge verification failed. Please reload the page and try again." },
      { status: 403 }
    );
  }

  // Strip the _challenge field before forwarding to the backend
  const { _challenge: _, ...cleanBody } = body;
  const cleanHeaders = new Headers(request.headers);
  cleanHeaders.delete("content-length"); // let undici recalculate from the smaller body
  const cleanedRequest = new NextRequest(request.url, {
    method: request.method,
    headers: cleanHeaders,
    body: JSON.stringify(cleanBody),
  });

  return proxyRequest(cleanedRequest, "/guest-audit");
}
