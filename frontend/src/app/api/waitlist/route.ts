import { createHash } from "crypto";
import { NextRequest, NextResponse } from "next/server";

// Server-side Mailchimp waitlist proxy for the coming-soon gate page.
// The API key is read from a SERVER-ONLY env var and never reaches the client.
// Returns JSON (the client form submits via fetch) — no redirects.
export const runtime = "nodejs";

const AUDIENCE_ID = process.env.MAILCHIMP_AUDIENCE_ID || "4c688f64f2";
const TAG = process.env.MAILCHIMP_TAG || "signal-coming-soon";
const API_KEY = process.env.MAILCHIMP_API_KEY || "";
// Single ("subscribed") vs double opt-in ("pending"). Default single for a waitlist.
const STATUS_IF_NEW = process.env.MAILCHIMP_STATUS_IF_NEW || "subscribed";

/** Mailchimp encodes the data center as the suffix of the API key (e.g. "-us18"). */
function dataCenterFromKey(key: string): string | null {
  const idx = key.lastIndexOf("-");
  return idx > -1 && idx < key.length - 1 ? key.slice(idx + 1) : null;
}

const ok = () => NextResponse.json({ status: "ok" });
const fail = (message: string, status: number) => NextResponse.json({ error: message }, { status });

export async function POST(request: NextRequest): Promise<NextResponse> {
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return fail("Invalid request.", 400);
  }

  // Honeypot: bots fill hidden fields — silently accept, do nothing.
  if (typeof body.hp === "string" && body.hp.trim()) {
    return ok();
  }

  const email = String(body.email || "")
    .trim()
    .toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return fail("Please enter a valid email address.", 400);
  }

  if (!API_KEY) {
    console.error("[waitlist] MAILCHIMP_API_KEY is not configured");
    return fail("Waitlist is temporarily unavailable.", 503);
  }
  const dc = dataCenterFromKey(API_KEY);
  if (!dc) {
    console.error("[waitlist] MAILCHIMP_API_KEY has no data-center suffix");
    return fail("Waitlist is temporarily unavailable.", 503);
  }

  const fname = String(body.fname || "").trim();
  const company = String(body.company || "").trim();
  const website = String(body.website || "").trim();

  const auth = "Basic " + Buffer.from(`anystring:${API_KEY}`).toString("base64");
  // Mailchimp's subscriber id is the MD5 of the lowercase email — the vendor's
  // required addressing scheme, not a security hash.
  const subscriberHash = createHash("md5").update(email).digest("hex");
  const listBase = `https://${dc}.api.mailchimp.com/3.0/lists/${AUDIENCE_ID}`;

  // Merge tags as configured on the Mailchimp audience:
  //   FNAME (First Name), COMPANY (Company) — optional
  //   MMERGE8 (Full Name), MMERGE7 (Website or Brand) — REQUIRED
  const mergeFields: Record<string, string> = {};
  if (fname) {
    mergeFields.FNAME = fname;
    mergeFields.MMERGE8 = fname; // "Full Name" (required)
  }
  if (company) mergeFields.COMPANY = company;
  if (website) mergeFields.MMERGE7 = website; // "Website or Brand" (required)

  const upsert = (fields: Record<string, string>) =>
    fetch(`${listBase}/members/${subscriberHash}`, {
      method: "PUT",
      headers: { Authorization: auth, "Content-Type": "application/json" },
      body: JSON.stringify({
        email_address: email,
        status_if_new: STATUS_IF_NEW,
        merge_fields: fields,
        tags: [TAG],
      }),
    });

  const looksLikeInvalidEmail = (detail: string) =>
    /looks fake|invalid|not.*valid.*email/i.test(detail) && !/merge/i.test(detail);

  try {
    const res = await upsert(mergeFields);
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      if (res.status === 400 && looksLikeInvalidEmail(detail)) {
        return fail("Please enter a valid work email address.", 400);
      }
      // Missing/invalid required merge fields (Full Name, Website or Brand).
      if (res.status === 400 && /merge|required/i.test(detail)) {
        return fail("Please fill in your name and website or brand.", 400);
      }
      console.warn("[waitlist] mailchimp upsert failed", {
        status: res.status,
        detail: detail.slice(0, 200),
      });
      return fail("Something went wrong. Please try again.", 502);
    }
    // Apply the tag explicitly so it also lands on already-existing members
    // (the PUT above only applies tags when creating a brand-new member).
    await fetch(`${listBase}/members/${subscriberHash}/tags`, {
      method: "POST",
      headers: { Authorization: auth, "Content-Type": "application/json" },
      body: JSON.stringify({ tags: [{ name: TAG, status: "active" }] }),
    }).catch(() => undefined);
    return ok();
  } catch {
    console.error("[waitlist] mailchimp request error");
    return fail("Something went wrong. Please try again.", 502);
  }
}
