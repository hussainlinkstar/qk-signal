const NODE_ENV = process.env.NODE_ENV ?? "development";

export function getJwtSigningKey(): Uint8Array | null {
  const rawSecret = (process.env.JWT_SECRET_KEY || process.env.JWT_SECRET || "").trim();
  if (!rawSecret) {
    if (NODE_ENV === "production") {
      console.error("Missing JWT secret configuration in production environment.");
    }
    return null;
  }
  return new TextEncoder().encode(rawSecret);
}
