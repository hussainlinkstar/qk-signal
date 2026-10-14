import { NextRequest, NextResponse } from "next/server";
import { PROXY_TIMEOUTS, proxyRequest } from "../proxy";

type RouteContext = {
  params: Promise<{
    path?: string[];
  }>;
};

const handler = async (request: NextRequest, context: RouteContext) => {
  const { path } = await context.params;
  const subpath = path?.join("/") ?? "";
  const requiresLongTimeout = subpath.startsWith("ai/") || subpath === "admin/billing/sync";
  const timeoutMs = requiresLongTimeout ? PROXY_TIMEOUTS.default : PROXY_TIMEOUTS.short;

  return proxyRequest(request, `/${subpath}`, { timeoutMs });
};

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;

export const OPTIONS = async (request: NextRequest, context: RouteContext) => {
  const { path } = await context.params;
  const subpath = path?.join("/") ?? "";
  const isEmbedRoute =
    subpath.startsWith("v1/embed/") ||
    subpath === "v1/embed" ||
    subpath.startsWith("embed/") ||
    subpath === "embed";

  if (!isEmbedRoute) {
    return handler(request, context);
  }

  const origin = request.headers.get("origin") ?? "*";
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Authorization,Content-Type,X-Embed-Key,X-Request-ID",
      Vary: "Origin",
    },
  });
};
