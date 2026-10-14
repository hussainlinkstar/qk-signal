import path from "node:path";
import { defineConfig } from "vitest/config";

const nodeTests = [
  "src/lib/targetMarket.test.ts",
  "src/lib/projectTargetCountry.test.ts",
  "src/lib/entitySuggestionRanking.test.ts",
  "src/lib/aioScore.test.ts",
  "src/lib/competitorQuestionWins.test.ts",
  "src/lib/projectScoreTrend.test.ts",
  "src/lib/roleMode.test.ts",
  "src/lib/planLocks.test.ts",
  "src/lib/auditRouting.test.ts",
  "src/lib/i18nFlags.test.ts",
  "src/lib/projectAuditFeature.test.ts",
];
const excludedTests = ["e2e/**", "node_modules/**", "dist/**", ".next/**"];

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    globals: true,
    exclude: excludedTests,
    projects: [
      {
        extends: true,
        test: {
          name: "node",
          environment: "node",
          include: nodeTests,
        },
      },
      {
        extends: true,
        test: {
          name: "ui",
          environment: "jsdom",
          setupFiles: ["./src/test/setup.ts"],
          exclude: [...excludedTests, ...nodeTests],
        },
      },
    ],

    // The suite was intermittently red, with the failing file changing between
    // runs. The cause is CPU contention rather than shared state: vitest runs one
    // worker per core, each page test renders a large tree in jsdom, and under
    // load a test that needs about a second in isolation overshoots the 5s
    // default. ReportsPageClient, for example, runs 11 tests in 3.18s on its own
    // and passes, but times out when the machine is saturated. A timed-out hook
    // also skips the rest of its file, which is why some runs reported fewer
    // tests than others.
    //
    // These are budgets, not retries. Assertions are unchanged, so a genuinely
    // broken test still fails, just after waiting longer. The alternative,
    // capping workers, slows every run to fix a minority of them.
    testTimeout: 20_000,
    hookTimeout: 30_000,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "server-only": path.resolve(__dirname, "./src/test/mocks/server-only.ts"),
    },
  },
});
