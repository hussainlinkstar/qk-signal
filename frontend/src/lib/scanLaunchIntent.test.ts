import { beforeEach, describe, expect, it } from "vitest";

import {
  clearScanLaunchIntent,
  isSameTarget,
  peekScanLaunchIntent,
  recordScanLaunchIntent,
  SCAN_LAUNCH_INTENT_KEY,
  SCAN_LAUNCH_INTENT_TTL_MS,
} from "@/lib/scanLaunchIntent";

/**
 * SIGV2-1159. The launch intent is the authority to start a scan without a
 * second confirmation, so each property it is trusted for is pinned here:
 * it can only come from our own code in this tab, it expires, it is single
 * use, and it names the target it was created for.
 */
describe("scanLaunchIntent", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("records an intent the page can read back", () => {
    recordScanLaunchIntent({ projectId: 42, target: "northwind.example" });

    expect(peekScanLaunchIntent()).toEqual(
      expect.objectContaining({ projectId: 42, target: "northwind.example" })
    );
  });

  it("reads nothing when nothing was recorded, which is the state a link arrives in", () => {
    expect(peekScanLaunchIntent()).toBeNull();
  });

  it("keeps the intent readable until it is consumed, since the prefill lands later", () => {
    recordScanLaunchIntent({ projectId: 42, target: "northwind.example" });

    expect(peekScanLaunchIntent()).not.toBeNull();
    expect(peekScanLaunchIntent()).not.toBeNull();

    clearScanLaunchIntent();

    expect(peekScanLaunchIntent()).toBeNull();
  });

  it("refuses an intent older than the expiry, and discards it", () => {
    window.sessionStorage.setItem(
      SCAN_LAUNCH_INTENT_KEY,
      JSON.stringify({
        projectId: 42,
        target: "northwind.example",
        createdAt: Date.now() - (SCAN_LAUNCH_INTENT_TTL_MS + 1),
      })
    );

    expect(peekScanLaunchIntent()).toBeNull();
    expect(window.sessionStorage.getItem(SCAN_LAUNCH_INTENT_KEY)).toBeNull();
  });

  it("accepts an intent inside the expiry", () => {
    window.sessionStorage.setItem(
      SCAN_LAUNCH_INTENT_KEY,
      JSON.stringify({
        projectId: 42,
        target: "northwind.example",
        createdAt: Date.now() - (SCAN_LAUNCH_INTENT_TTL_MS - 1_000),
      })
    );

    expect(peekScanLaunchIntent()).not.toBeNull();
  });

  it("refuses a record stamped in the future", () => {
    window.sessionStorage.setItem(
      SCAN_LAUNCH_INTENT_KEY,
      JSON.stringify({
        projectId: 42,
        target: "northwind.example",
        createdAt: Date.now() + 60_000,
      })
    );

    expect(peekScanLaunchIntent()).toBeNull();
  });

  it("refuses a malformed or incomplete record, and discards it", () => {
    for (const raw of [
      "not json",
      "null",
      '"a string"',
      JSON.stringify({ target: "northwind.example", createdAt: Date.now() }),
      JSON.stringify({ projectId: 42, createdAt: Date.now() }),
      JSON.stringify({ projectId: 42, target: "   ", createdAt: Date.now() }),
      JSON.stringify({ projectId: "42", target: "northwind.example", createdAt: Date.now() }),
      JSON.stringify({ projectId: 0, target: "northwind.example", createdAt: Date.now() }),
      JSON.stringify({ projectId: 42, target: "northwind.example" }),
    ]) {
      window.sessionStorage.setItem(SCAN_LAUNCH_INTENT_KEY, raw);

      expect(peekScanLaunchIntent(), raw).toBeNull();
      expect(window.sessionStorage.getItem(SCAN_LAUNCH_INTENT_KEY), raw).toBeNull();
    }
  });

  it("records nothing for an empty target", () => {
    recordScanLaunchIntent({ projectId: 42, target: "   " });

    expect(peekScanLaunchIntent()).toBeNull();
  });

  it("matches targets by host, ignoring scheme, www and path", () => {
    expect(isSameTarget("https://www.northwind.example/rooms", "northwind.example")).toBe(true);
    expect(isSameTarget("northwind.example", "HTTPS://NorthWind.Example")).toBe(true);
    expect(isSameTarget("https://coastline.example", "northwind.example")).toBe(false);
    expect(isSameTarget("https://northwind.example.attacker.tld", "northwind.example")).toBe(false);
    expect(isSameTarget("", "northwind.example")).toBe(false);
    expect(isSameTarget("northwind.example", "")).toBe(false);
  });
});
