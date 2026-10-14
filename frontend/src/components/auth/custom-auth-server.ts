import { cookies } from "next/headers";
import { jwtVerify } from "jose";
import { getJwtSigningKey } from "@/lib/server-secrets";

const encodedSecret = getJwtSigningKey();

export async function auth() {
  const cookieStore = await cookies();
  const token = cookieStore.get("auth_token")?.value;

  if (!token || token === "undefined" || token === "null") {
    return { userId: null, error: "no_token" };
  }

  try {
    if (!encodedSecret) {
      return { userId: null, error: "missing_secret" };
    }
    const verified = await jwtVerify(token, encodedSecret);
    const userId = String(verified.payload.sub ?? "");
    return { userId: userId || null };
  } catch (err: any) {
    console.error("JWT Verification failed:", err.message);
    return { userId: null, error: "invalid_token" };
  }
}
