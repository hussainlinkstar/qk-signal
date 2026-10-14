import { NextRequest } from "next/server";
import { proxyRequest } from "../../proxy";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(request: NextRequest) {
  return proxyRequest(request, "/audit/jobs");
}

export async function GET(request: NextRequest) {
  return proxyRequest(request, "/audit/jobs/active");
}
