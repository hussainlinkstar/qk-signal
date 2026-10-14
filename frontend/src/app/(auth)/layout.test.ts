import { describe, expect, it } from "vitest";

import { metadata } from "@/app/(auth)/layout";
import { metadata as loginMetadata } from "@/app/(auth)/login/page";

/**
 * The auth pages went live indexable. The private preview gate had been
 * redirecting every URL to a "Coming soon" page, so nothing under (auth) had
 * ever been crawlable and the omission was invisible until the gate came off.
 */
describe("auth route group metadata", () => {
  it("keeps sign-in and recovery pages out of the index", () => {
    expect(metadata.robots).toEqual({ index: false, follow: true });
  });

  it("does not let the pages override robots with their own metadata", () => {
    // Next merges parent and child metadata field by field, so a page that
    // defines only a title and description still inherits robots from here.
    expect(loginMetadata.title).toBe("Sign In");
    expect(loginMetadata.robots).toBeUndefined();
  });
});
