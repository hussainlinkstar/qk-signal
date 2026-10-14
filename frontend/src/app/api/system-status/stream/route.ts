import { NextRequest } from "next/server";
import { createStatusStreamResponse } from "../utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return createStatusStreamResponse(request, {
    path: "/system-status",
    audience: "public",
  });
}
