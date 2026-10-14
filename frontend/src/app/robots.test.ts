import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Production served `Sitemap: http://localhost:3000/sitemap.xml`. robots.txt has
 * no async work, so Next prerendered it during the image build, where
 * frontend/.env is absent and the base URL falls back to localhost. The value
 * was then frozen into the deployed file even though the runtime env is right.
 */
describe("robots.txt", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  async function loadRobots() {
    const mod = await import("@/app/robots");
    return mod;
  }

  it("is rendered per request so it reads the runtime environment", async () => {
    const { dynamic } = await loadRobots();
    expect(dynamic).toBe("force-dynamic");
  });

  it("points the sitemap at the configured public URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://qiko.ai/signal");
    const { default: robots } = await loadRobots();
    expect(robots().sitemap).toBe("https://qiko.ai/signal/sitemap.xml");
  });

  it("reads the environment on every call, not once at module load", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://first.example");
    const { default: robots } = await loadRobots();
    expect(robots().sitemap).toBe("https://first.example/sitemap.xml");

    // The regression was a module-scope constant, which would keep returning
    // the first value here.
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://second.example");
    expect(robots().sitemap).toBe("https://second.example/sitemap.xml");
  });

  it("keeps the app surfaces disallowed", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://qiko.ai/signal");
    const { default: robots } = await loadRobots();
    const rules = Array.isArray(robots().rules) ? robots().rules : [robots().rules];
    expect(rules[0]).toMatchObject({ userAgent: "*", disallow: ["/admin", "/dashboard", "/api"] });
  });
});
