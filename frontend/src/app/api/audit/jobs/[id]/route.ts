import { NextRequest } from "next/server";
import { PROXY_TIMEOUTS, proxyRequest } from "../../../proxy";

type RouteContext = {
  params: Promise<{
    id: string;
  }>;
};

export const runtime = "nodejs";

export async function GET(request: NextRequest, context: RouteContext) {
  const { id } = await context.params;
  return proxyRequest(request, `/audit/jobs/${id}`, {
    timeoutMs: PROXY_TIMEOUTS.short,
  });
}
