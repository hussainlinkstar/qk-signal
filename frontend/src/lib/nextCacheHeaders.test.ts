import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../../next.config.mjs";

afterEach(() => vi.unstubAllEnvs());

describe("Next.js asset cache headers", () => {
  it("leaves development assets to Next.js so stale client bundles cannot outlive edits", async () => {
    vi.stubEnv("NODE_ENV", "development");
    const headers = await nextConfig.headers();
    expect(headers.find((rule) => rule.source === "/_next/static/:path*")).toBeUndefined();
    expect(headers.find((rule) => rule.source === "/(.*)")?.headers).toContainEqual({
      key: "X-Content-Type-Options",
      value: "nosniff",
    });
  });

  it("retains long-lived caching for immutable production assets", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const headers = await nextConfig.headers();
    expect(headers.find((rule) => rule.source === "/_next/static/:path*")?.headers).toContainEqual({
      key: "Cache-Control",
      value: "public, max-age=31536000, immutable",
    });
  });
});
