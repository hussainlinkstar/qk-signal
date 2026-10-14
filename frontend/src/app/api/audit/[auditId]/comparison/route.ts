import { NextRequest } from "next/server";
import { PROXY_TIMEOUTS, proxyRequest } from "../../../proxy";

type RouteContext = { params: Promise<{ auditId: string }> };

export const runtime = "nodejs";

export async function GET(request: NextRequest, context: RouteContext) {
  const { auditId } = await context.params;
  return proxyRequest(request, `/audit/${auditId}/comparison`, {
    timeoutMs: PROXY_TIMEOUTS.short,
  });
}
