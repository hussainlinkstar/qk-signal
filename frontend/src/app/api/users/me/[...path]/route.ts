import { NextRequest } from "next/server";
import { PROXY_TIMEOUTS, proxyRequest } from "../../../proxy";

type RouteContext = {
  params: Promise<{
    path?: string[];
  }>;
};

const handler = async (request: NextRequest, context: RouteContext) => {
  const { path } = await context.params;
  const subpath = path?.join("/") ?? "";
  return proxyRequest(request, `/users/me/${subpath}`, { timeoutMs: PROXY_TIMEOUTS.short });
};

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
