import { NextRequest } from "next/server";

import { PROXY_TIMEOUTS, proxyRequest } from "../proxy";

export async function POST(request: NextRequest) {
  return proxyRequest(request, "/contact", { timeoutMs: PROXY_TIMEOUTS.default });
}
