// Design-comparison sharding: split the screen-groups catalogue across N CI
// runners so wall clock is the slowest shard rather than the whole serial
// catalogue. Pure module on purpose - no playwright, no I/O - so the node
// test runner can exercise it without the app, the stub backend or a browser.
//
// Cost model: every state costs one capture per viewport per locale (4
// captures, roughly 14s), so a group's cost is proportional to
// `states.length` and group sizes are very uneven (groups of 5, 3, 2 and many
// of 1). Round-robin over groups would leave one shard holding two 5-state
// groups while another holds singles, so the assignment is greedy
// longest-processing-time instead: largest groups first, each to the
// currently lightest bin. Deterministic - same catalogue, same shards.

// Parse `--shard=<index>/<count>` from an argv array. Returns null when the
// flag is absent (unsharded run). Anything else is a usage error, never a
// silent unsharded run: a malformed flag must exit non-zero, because
// continuing would run the full catalogue in every matrix leg.
export function parseShardArg(argv) {
  const arg = argv.find((a) => a.startsWith("--shard="));
  if (!arg) return null;
  const value = arg.slice("--shard=".length);
  const match = /^(\d+)\/(\d+)$/.exec(value);
  const index = match ? Number(match[1]) : NaN;
  const count = match ? Number(match[2]) : NaN;
  if (!match || count < 1 || index < 1 || index > count) {
    throw new Error(
      `invalid --shard value "${value}": expected --shard=<index>/<count> ` +
        `with count >= 1 and 1 <= index <= count`
    );
  }
  return { index, count };
}

// Greedy longest-processing-time partition. Returns `count` bins of groups.
// Groups sort by state count descending, ties by catalogue position; each
// lands in the bin with the smallest accumulated state count, ties by lowest
// bin index.
function partition(groups, count) {
  const bins = Array.from({ length: count }, () => ({ total: 0, groups: [] }));
  const ordered = groups
    .map((group, position) => ({ group, position }))
    .sort((a, b) => b.group.states.length - a.group.states.length || a.position - b.position);
  for (const { group } of ordered) {
    let target = 0;
    for (let b = 1; b < count; b++) {
      if (bins[b].total < bins[target].total) target = b;
    }
    bins[target].groups.push(group);
    bins[target].total += group.states.length;
  }
  return bins.map((bin) => bin.groups);
}

// The groups shard `index` (1-based) of `count` owns, back in catalogue order
// so reports and logs read like an unsharded run.
export function shardGroups(groups, { index, count }) {
  const bin = partition(groups, count)[index - 1];
  const position = new Map(groups.map((group, i) => [group, i]));
  return [...bin].sort((a, b) => position.get(a) - position.get(b));
}

// Safety property for a gate that exists to stop screens diverging unseen:
// prove the `count` bins are a true partition of `groups` - every group in
// exactly one bin, none lost, none duplicated. A drifting or hardcoded split
// would silently stop comparing a screen, which is exactly the class of
// defect SIGV2-1115 exists to prevent. Cheap (O(count * groups)), so
// compare.mjs runs it on every sharded invocation, not just in tests.
export function assertPartition(groups, count) {
  const bins = partition(groups, count);
  const seen = new Set();
  for (const bin of bins) {
    for (const group of bin) {
      const id = group.screen.id;
      if (seen.has(group)) {
        throw new Error(`shard partition duplicated group "${id}" across bins`);
      }
      if (!groups.includes(group)) {
        throw new Error(`shard partition produced group "${id}" not in the catalogue`);
      }
      seen.add(group);
    }
  }
  for (const group of groups) {
    if (!seen.has(group)) {
      throw new Error(`shard partition lost group "${group.screen.id}"`);
    }
  }
}
