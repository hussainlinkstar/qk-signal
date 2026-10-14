/**
 * SIGV2-1128: the frontend counterpart of
 * backend/tests/test_email_suite_end_to_end.py, which keeps credit language out
 * of every customer-facing email. The same rule applies to the Billing page,
 * the surface a customer is most likely to read as a bill: scans are the only
 * customer-facing limit, credits are internal monitoring.
 *
 * Two assertions, for the same reason the email suite needs two. A rendered
 * surface cannot reveal a credit-denominated variable, because that variable
 * renders as a bare number. The source can.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommitmentTierSelector from "@/components/billing/CommitmentTierSelector";
import { tEn } from "@/test/i18nEn";
import en from "@/i18n/en.json";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn, i18n: { language: "en" } }),
}));

const SRC_ROOT = path.resolve(__dirname, "../..");

// Every file that can render on the customer Billing page.
const BILLING_SURFACE_DIRS = [
  path.join(SRC_ROOT, "components", "billing"),
  path.join(SRC_ROOT, "app", "(app)", "dashboard", "billing"),
];

// `CreditCard` is a lucide icon identifier used as the Billing tab glyph. It
// names a payment card, never a Qiko credit, and never reaches the DOM as text.
const ALLOWED_IDENTIFIERS = /\bCreditCard\b/g;

const collectFiles = (dir: string): string[] =>
  fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((entry) => {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) return collectFiles(full);
      if (!/\.(ts|tsx)$/.test(entry.name)) return [];
      if (/\.test\.(ts|tsx)$/.test(entry.name)) return [];
      return [full];
    })
    .sort();

/**
 * Strip comments so an explanatory note about credits does not read as a leak,
 * while a string or an identifier still does. String and template literals are
 * preserved, which is the point: copy lives in them.
 */
const stripComments = (source: string): string => {
  let out = "";
  let index = 0;
  let quote: string | null = null;
  while (index < source.length) {
    const char = source[index];
    const next = source[index + 1];
    if (quote) {
      if (char === "\\") {
        out += char + (next ?? "");
        index += 2;
        continue;
      }
      if (char === quote) quote = null;
      out += char;
      index += 1;
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      quote = char;
      out += char;
      index += 1;
      continue;
    }
    if (char === "/" && next === "/") {
      while (index < source.length && source[index] !== "\n") index += 1;
      continue;
    }
    if (char === "/" && next === "*") {
      index += 2;
      while (index < source.length && !(source[index] === "*" && source[index + 1] === "/")) {
        index += 1;
      }
      index += 2;
      continue;
    }
    out += char;
    index += 1;
  }
  return out;
};

const billingFiles = BILLING_SURFACE_DIRS.flatMap(collectFiles);

describe("billing surfaces never mention credits", () => {
  it("covers the billing components and the billing route", () => {
    expect(billingFiles.length).toBeGreaterThan(5);
    expect(
      billingFiles.some((file) => file.endsWith(path.join("billing", "CommitmentTierSelector.tsx")))
    ).toBe(true);
    expect(billingFiles.some((file) => file.endsWith(path.join("billing", "page.tsx")))).toBe(true);
  });

  it.each(billingFiles)("%s carries no credit-denominated code or copy", (file) => {
    const source = stripComments(fs.readFileSync(file, "utf-8")).replace(
      ALLOWED_IDENTIFIERS,
      "PaymentCard"
    );
    const offenders = source
      .split("\n")
      .map((line, position) => ({ line: line.trim(), position: position + 1 }))
      .filter(({ line }) => /credit/i.test(line));
    expect(offenders, `${file} reads or renders credit-denominated content`).toEqual([]);
  });

  it("keeps the word out of the English interface catalogue", () => {
    expect(/credit/i.test(JSON.stringify(en))).toBe(false);
  });
});

describe("the commitment surface renders no credit figure", () => {
  const commitment = {
    id: 11,
    tier: "scale",
    committed_credits: 5000,
    rate_per_credit: 0.08,
    monthly_fee_usd: 400,
    overage_rate: 0.1,
    status: "active",
    cancel_at_period_end: false,
    cycle_start: "2026-03-01T00:00:00Z",
    cycle_end: "2026-04-01T00:00:00Z",
    credits_used: 4100,
    credits_remaining: 900,
    overage_credits: 0,
    usage_pct: 82,
    nearing_limit: true,
    in_overage: false,
    pending_tier: null,
    pending_change_effective_at: null,
  };

  const surface = {
    eligible: true,
    locked_reason: null,
    current_plan: "plan_specialist",
    commitment,
    tiers: [
      {
        tier: "growth",
        label: "Growth",
        committed_credits: 2000,
        rate_per_credit: 0.09,
        discount_pct: 10,
        monthly_fee_usd: 180,
        overage_rate: 0.1,
      },
      {
        tier: "scale",
        label: "Scale",
        committed_credits: 5000,
        rate_per_credit: 0.08,
        discount_pct: 20,
        monthly_fee_usd: 400,
        overage_rate: 0.1,
      },
    ],
  };

  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(surface), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders neither the word nor any credit quantity", async () => {
    render(
      <CommitmentTierSelector
        getAuthHeaders={async () => ({ Authorization: "Bearer token-123" })}
      />
    );

    await screen.findByText("Nearing commitment");
    const rendered = document.body.textContent ?? "";

    expect(rendered).not.toMatch(/credit/i);
    // Credit quantities and the per-credit rates behind this commitment.
    for (const figure of ["5,000", "4,100", "900", "2,000", "82%", "$0.08", "$0.09", "$0.10"]) {
      expect(rendered, `rendered ${figure}`).not.toContain(figure);
    }
    // The fee is a real contract amount in dollars, so it stays.
    expect(rendered).toContain("$400.00");
  });
});
