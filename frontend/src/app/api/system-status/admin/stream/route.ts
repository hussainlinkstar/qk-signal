import { NextRequest } from "next/server";
import { createStatusStreamResponse, requireAdminToken } from "../../utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const auth = await requireAdminToken(request);
  if ("response" in auth) {
    return auth.response;
  }

  return createStatusStreamResponse(request, {
    path: "/system-status/admin",
    audience: "admin",
    token: auth.token,
  });
}
