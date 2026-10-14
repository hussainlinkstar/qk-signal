import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { BASE_PATH } from "@/lib/basePath";
import { GATE_COOKIE, GATE_PATH, computeGateToken, getGatePassword } from "@/lib/signalGate";

// Only allow internal redirect targets.
function safeNext(next: string): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) {
    return "/";
  }
  return next;
}

// Relative-path redirect so it works behind the Cloudflare/Traefik/Caddy proxy
// chain (the internal request host is not the public one).
function redirectTo(path: string, init?: ResponseInit): NextResponse {
  const response = new NextResponse(null, { status: 303, ...init });
  response.headers.set("Location", path);
  return response;
}

export async function POST(request: NextRequest) {
  const form = await request.formData();
  const password = String(form.get("password") ?? "");
  const next = safeNext(String(form.get("next") ?? "/"));

  const gatePassword = getGatePassword();

  // Wrong / missing password → back to the gate with an error flag.
  if (!gatePassword || password !== gatePassword) {
    return redirectTo(`${BASE_PATH}${GATE_PATH}?error=1&next=${encodeURIComponent(next)}`);
  }

  const token = await computeGateToken(gatePassword);
  const response = redirectTo(`${BASE_PATH}${next}`);
  response.cookies.set(GATE_COOKIE, token, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: BASE_PATH || "/",
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });
  return response;
}
