import { describe, expect, it } from "vitest";

import en from "@/i18n/en.json";
import {
  PROJECT_SETUP_FAILURE_I18N_KEYS,
  resolveProjectSetupFailureKey,
  resolveProjectSetupFailureReason,
} from "@/lib/projectSetupFailure";
import { HttpRequestError } from "@/services/http";
import { tEn } from "@/test/i18nEn";

describe("resolveProjectSetupFailureReason", () => {
  it("names the permission case so the customer knows who to ask", () => {
    expect(resolveProjectSetupFailureReason(new HttpRequestError(403, "x"))).toBe("noPermission");
  });

  it("treats a rejected payload as a target problem", () => {
    for (const status of [400, 409, 422]) {
      expect(resolveProjectSetupFailureReason(new HttpRequestError(status, "x"))).toBe(
        "invalidTarget"
      );
    }
  });

  it("treats an expired session as a sign-in problem", () => {
    expect(resolveProjectSetupFailureReason(new HttpRequestError(401, "x"))).toBe("signedOut");
  });

  it("falls back to the generic reason for anything else", () => {
    expect(resolveProjectSetupFailureReason(new HttpRequestError(500, "x"))).toBe("generic");
    expect(resolveProjectSetupFailureReason(new TypeError("Failed to fetch"))).toBe("generic");
    expect(resolveProjectSetupFailureReason(undefined)).toBe("generic");
  });
});

describe("project setup failure copy", () => {
  const messages = Object.values(PROJECT_SETUP_FAILURE_I18N_KEYS).map((key) => tEn(key));

  it("resolves every reason to real copy", () => {
    expect(messages).toHaveLength(4);
    for (const key of Object.values(PROJECT_SETUP_FAILURE_I18N_KEYS)) {
      // tEn returns the key itself when the key is missing from en.json.
      expect(tEn(key)).not.toBe(key);
    }
  });

  it("never reads as a quota refusal and never says credit", () => {
    // The remaining-scans line renders directly above this message, which is
    // why a tester read an unrelated failure as being out of scans. Scans are
    // the only customer-facing limit and "credit" is not customer wording.
    for (const message of messages) {
      expect(message.toLowerCase()).not.toContain("credit");
      expect(message.toLowerCase()).not.toContain("quota");
      expect(message.toLowerCase()).not.toContain("out of scans");
      expect(message).toContain("No scan was used.");
    }
  });

  it("never leaks the internal wording the customer could not act on", () => {
    const serialized = JSON.stringify(en);
    expect(serialized).not.toContain("Failed to resolve or create a project");
    expect(serialized).not.toContain("Project ID is required");
    for (const message of messages) {
      expect(message).not.toContain("SIGV2");
      expect(message.toLowerCase()).not.toContain("project id");
    }
  });

  it("maps a classified error straight to its key", () => {
    expect(resolveProjectSetupFailureKey(new HttpRequestError(403, "x"))).toBe(
      PROJECT_SETUP_FAILURE_I18N_KEYS.noPermission
    );
  });
});
