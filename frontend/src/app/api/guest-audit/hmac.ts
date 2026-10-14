import { createHmac, randomBytes } from "crypto";

const CHALLENGE_SECRET =
  process.env.GUEST_AUDIT_CHALLENGE_SECRET ||
  process.env.JWT_SECRET_KEY ||
  "dev-guest-audit-challenge-fallback";

const TOKEN_TTL_MS = 5 * 60 * 1000; // 5 minutes

type ChallengePayload = {
  nonce: string;
  ip: string;
  ts: number;
};

function sign(payload: ChallengePayload): string {
  const data = JSON.stringify(payload);
  const encoded = Buffer.from(data).toString("base64url");
  const signature = createHmac("sha256", CHALLENGE_SECRET).update(encoded).digest("base64url");
  return `${encoded}.${signature}`;
}

function parse(token: string): ChallengePayload | null {
  const [encoded, signature] = token.split(".");
  if (!encoded || !signature) {
    return null;
  }

  const expected = createHmac("sha256", CHALLENGE_SECRET).update(encoded).digest("base64url");
  if (expected !== signature) {
    return null;
  }

  try {
    const raw = Buffer.from(encoded, "base64url").toString("utf-8");
    return JSON.parse(raw) as ChallengePayload;
  } catch {
    return null;
  }
}

export function issueChallenge(ip: string): string {
  const payload: ChallengePayload = {
    nonce: randomBytes(16).toString("hex"),
    ip,
    ts: Date.now(),
  };
  return sign(payload);
}

export function verifyChallenge(
  token: string,
  ip: string
): { ok: true } | { ok: false; reason: string } {
  const payload = parse(token);
  if (!payload) {
    return { ok: false, reason: "invalid_signature" };
  }

  const age = Date.now() - payload.ts;
  if (age > TOKEN_TTL_MS) {
    return { ok: false, reason: "expired" };
  }

  if (age < 0) {
    return { ok: false, reason: "clock_skew" };
  }

  if (payload.ip !== ip) {
    return { ok: false, reason: "ip_mismatch" };
  }

  return { ok: true };
}
