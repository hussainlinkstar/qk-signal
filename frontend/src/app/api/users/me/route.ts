import { NextRequest } from "next/server";
import { PROXY_TIMEOUTS, proxyRequest } from "../../proxy";

export async function GET(request: NextRequest) {
  return proxyRequest(request, "/users/me", { timeoutMs: PROXY_TIMEOUTS.short });
}

export async function PATCH(request: NextRequest) {
  return proxyRequest(request, "/users/me", { timeoutMs: PROXY_TIMEOUTS.short });
}

export async function POST(request: NextRequest) {
  return proxyRequest(request, "/users/me", { timeoutMs: PROXY_TIMEOUTS.short });
}

export async function DELETE(request: NextRequest) {
  return proxyRequest(request, "/users/me", { timeoutMs: PROXY_TIMEOUTS.short });
}
