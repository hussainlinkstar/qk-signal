import { NextRequest } from "next/server";

import { forwardAuthExchange } from "../_route-utils";

export async function POST(request: NextRequest) {
  return forwardAuthExchange(request, "/auth/verify-email", { expectTokenPayload: false });
}
