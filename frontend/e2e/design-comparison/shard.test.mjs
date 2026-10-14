// node:test, not vitest, on purpose: frontend/vitest.config.ts excludes
// `e2e/**`, so a vitest spec here would never be collected. Run via
// `npm run test:design-shard` (`node --test`), which frontend-ci invokes.
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { assertPartition, parseShardArg, shardGroups } from "./shard.mjs";
import { screenGroups } from "./screens.mjs";

describe("parseShardArg", () => {
  it("returns null when no --shard flag is present", () => {
    assert.equal(parseShardArg([]), null);
    assert.equal(parseShardArg(["--reference-only", "--screens=a,b"]), null);
  });

  it("parses a well-formed shard", () => {
    assert.deepEqual(parseShardArg(["--shard=1/4"]), { index: 1, count: 4 });
    assert.deepEqual(parseShardArg(["--shard=4/4"]), { index: 4, count: 4 });
  });

  for (const bad of ["0/4", "5/4", "1/0", "1", "a/b", "1/4/2", "-1/4", "1/4 "]) {
    it(`rejects "${bad}"`, () => {
      assert.throws(() => parseShardArg([`--shard=${bad}`]), /--shard/);
    });
  }
});

describe("shardGroups against the real catalogue", () => {
  const groups = screenGroups();
  const largest = Math.max(...groups.map((g) => g.states.length));

  for (const count of [1, 2, 3, 4, 5, 6]) {
    it(`partitions the catalogue for count=${count}`, () => {
      assertPartition(groups, count);
      const bins = Array.from({ length: count }, (_, i) =>
        shardGroups(groups, { index: i + 1, count })
      );
      // Union equals the catalogue exactly, pairwise disjoint, none empty.
      const flat = bins.flat();
      assert.equal(flat.length, groups.length);
      assert.equal(new Set(flat).size, groups.length);
      for (const group of groups) assert.ok(flat.includes(group));
      for (const bin of bins) assert.ok(bin.length > 0);
      // Balanced by state count: the spread between the heaviest and lightest
      // shard stays within one group's cost, the LPT bound.
      const totals = bins.map((bin) => bin.reduce((sum, g) => sum + g.states.length, 0));
      assert.ok(Math.max(...totals) - Math.min(...totals) <= largest);
    });
  }

  it("returns groups in catalogue order within each shard", () => {
    const position = new Map(groups.map((g, i) => [g, i]));
    for (let index = 1; index <= 4; index++) {
      const bin = shardGroups(groups, { index, count: 4 });
      const positions = bin.map((g) => position.get(g));
      assert.deepEqual(
        positions,
        [...positions].sort((a, b) => a - b)
      );
    }
  });

  it("is deterministic", () => {
    for (let index = 1; index <= 4; index++) {
      const a = shardGroups(groups, { index, count: 4 }).map((g) => g.screen.id);
      const b = shardGroups(groups, { index, count: 4 }).map((g) => g.screen.id);
      assert.deepEqual(a, b);
    }
  });
});
