import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  MINIMUM_PLAN_BY_FEATURE,
  PLAN_DISPLAY_NAMES,
  minimumPlanForCapability,
  requiredPlanLabelForCapability,
} from "@/lib/planCapabilities";
import { PLAN_LOCK_CAPABILITY_KEYS, getPlanLockContent, isPlanUpgradeError } from "@/lib/planLocks";

/**
 * The tier names this recognised were the retired ones (Neural Core, Synapse
 * Pro, Singularity Elite), so real backend plan-lock messages naming the current
 * tiers fell through and the user saw a raw error string where the upgrade card
 * belongs. The messages below are copied from the backend.
 */
describe("isPlanUpgradeError", () => {
  it("recognises the plan-lock messages the backend actually sends", () => {
    // backend/routers/benchmark_router.py
    expect(
      isPlanUpgradeError(new Error("Benchmark intelligence requires Specialist or Executive."))
    ).toBe(true);
    // backend/routers/api_router.py
    expect(isPlanUpgradeError(new Error("Feature available in Specialist"))).toBe(true);
    expect(isPlanUpgradeError(new Error("AI Search Volatility Index requires Specialist"))).toBe(
      true
    );
  });

  it("still recognises the retired tier names on their own", () => {
    expect(isPlanUpgradeError(new Error("Available on Synapse Pro"))).toBe(true);
    expect(isPlanUpgradeError(new Error("Neural Core only"))).toBe(true);
  });

  it("does not mistake ordinary errors that happen to contain a tier word", () => {
    // The reason the current tier names require requirement wording: these must
    // surface as errors, not as an upgrade prompt that hides them.
    expect(isPlanUpgradeError(new Error("Executive summary generation failed"))).toBe(false);
    expect(isPlanUpgradeError(new Error("Specialist review timed out"))).toBe(false);
    expect(isPlanUpgradeError(new Error("Standard rate applied after commitment"))).toBe(false);
  });

  it("treats a 402 as a plan lock whatever the message says", () => {
    const paymentRequired = Object.assign(new Error("boom"), { status: 402 });
    expect(isPlanUpgradeError(paymentRequired)).toBe(true);
  });

  it("ignores non-errors", () => {
    expect(isPlanUpgradeError("requires Specialist")).toBe(false);
    expect(isPlanUpgradeError(null)).toBe(false);
  });
});

// SIGV2-1168: the done-for-you execution offer was withdrawn. Its only
// remaining consumer is PlanProgressView's locked state, so the copy must
// describe the read-only Advisor plan-progress view on Executive - not CMS,
// Jira or Slack execution, and no price.
describe("doneForYouExecution lock copy", () => {
  const lock = getPlanLockContent("doneForYouExecution");

  it("names Executive and describes the plan-progress view only", () => {
    expect(lock.requiredPlanLabel).toBe("Executive");
    expect(lock.ctaLabel).toBe("Upgrade to Executive");
    expect(lock.description).toMatch(/Advisor action plan/i);
    for (const field of [lock.title, lock.description, lock.ctaLabel, lock.helperText]) {
      expect(field).not.toContain("$");
      expect(field).not.toContain("CMS");
      expect(field).not.toContain("Jira");
      expect(field).not.toContain("Slack");
    }
  });
});

// SIGV2-1221. The defect class this pins down: a lock card is the only place
// the product tells a customer which plan to buy, and every plan name on one
// used to be hand-written copy. Nothing checked it against the entitlement the
// surface is actually gated on, so "PDF audit exports require Standard" sat
// next to a capability every plan grants, and "Project monitoring requires
// Standard" sat next to another. A wrong plan name is a passing test until
// something computes the right one.
describe("every plan lock names the plan its own entitlement requires", () => {
  const PLAN_LOCK_FEATURES = Object.keys(
    PLAN_LOCK_CAPABILITY_KEYS
  ) as (keyof typeof PLAN_LOCK_CAPABILITY_KEYS)[];

  it.each(PLAN_LOCK_FEATURES)("%s names the minimum plan for its capability", (feature) => {
    const capabilityKey = PLAN_LOCK_CAPABILITY_KEYS[feature];
    const expected = requiredPlanLabelForCapability(capabilityKey);
    const lock = getPlanLockContent(feature);

    expect(expected, `${feature} gates on ${capabilityKey}`).not.toBeNull();
    expect(lock.requiredPlanLabel).toBe(expected);
    expect(lock.title).toContain(expected as string);
    expect(lock.ctaLabel).toBe(`Upgrade to ${expected}`);
    expect(lock.helperText).toContain(expected as string);
  });

  // A capability the free plan already grants has no plan to upgrade to, so it
  // may not have a lock at all. `liveEngineTracking` was removed on SIGV2-1108
  // for this reason and `pdfExports` on SIGV2-1221.
  it("has no lock for a capability every plan already grants", () => {
    for (const feature of PLAN_LOCK_FEATURES) {
      const capabilityKey = PLAN_LOCK_CAPABILITY_KEYS[feature];
      expect(minimumPlanForCapability(capabilityKey), feature).not.toBe("plan_starter");
    }
    expect(minimumPlanForCapability("has_pdf_audit_reports")).toBe("plan_starter");
    expect(minimumPlanForCapability("has_live_engine_tracking")).toBe("plan_starter");
  });

  // SIGV2-1211 is changing Standard and Specialist prices and making Executive
  // contact-only. A price printed in an upgrade prompt is a second, unmanaged
  // copy of the price list, and the approved MVP lock cards never carry one:
  // `Signal AIO Detail.html`, `Signal SEO Detail.html` and `Signal Gate.html`
  // all say "Upgrade to <plan>" and stop there.
  it("never prints a price", () => {
    for (const feature of PLAN_LOCK_FEATURES) {
      const lock = getPlanLockContent(feature);
      for (const field of [lock.title, lock.description, lock.ctaLabel, lock.helperText ?? ""]) {
        expect(field, feature).not.toMatch(/\$|\/mo\b|per month/i);
      }
    }
  });

  // The backend tells a locked audit section which plan it needs. When it does,
  // that answer wins over anything computed here, and it has to reach every
  // line of the card rather than just the eyebrow.
  it("rebuilds the whole card around a served plan name", () => {
    const lock = getPlanLockContent("entities", { requiredPlanLabel: "Executive" });

    expect(lock.requiredPlanLabel).toBe("Executive");
    expect(lock.title).toBe("Entity extraction requires Executive");
    expect(lock.ctaLabel).toBe("Upgrade to Executive");
    expect(lock.helperText).toBe("Entity extraction unlocks on Executive and above.");
  });

  it("falls back to the derived plan when the payload named none", () => {
    expect(getPlanLockContent("entities", { requiredPlanLabel: "  " }).requiredPlanLabel).toBe(
      "Specialist"
    );
  });
});

// The frontend table is a mirror, and a mirror that drifts is worse than no
// mirror: it would name a plan the backend stopped requiring with nothing to
// catch it. Pin it against the file it mirrors.
describe("MINIMUM_PLAN_BY_FEATURE mirrors the backend", () => {
  const backendSource = readFileSync(
    resolve(process.cwd(), "../backend/app/config/plans.py"),
    "utf8"
  );

  const parseBackendTable = (): Record<string, string> => {
    const block = backendSource.match(
      /MINIMUM_PLAN_BY_FEATURE: Final\[dict\[str, str\]\] = \{([\s\S]*?)\n\}/
    );
    expect(block, "MINIMUM_PLAN_BY_FEATURE block in backend/app/config/plans.py").not.toBeNull();

    const entries: Record<string, string> = {};
    for (const line of (block as RegExpMatchArray)[1].split("\n")) {
      const match = line.match(/^\s*"([a-z0-9_]+)":\s*"(plan_[a-z_]+)",\s*$/);
      if (match) {
        entries[match[1]] = match[2];
      }
    }
    return entries;
  };

  it("declares the same minimum plan for every capability the backend declares", () => {
    const backendTable = parseBackendTable();

    expect(Object.keys(backendTable).length).toBeGreaterThan(20);
    expect(MINIMUM_PLAN_BY_FEATURE).toEqual(backendTable);
  });

  it("uses the plan names the backend presents", () => {
    for (const [plan, name] of Object.entries(PLAN_DISPLAY_NAMES)) {
      expect(backendSource, plan).toContain(`"${plan}": {\n        "name": "${name}",`);
    }
  });
});
