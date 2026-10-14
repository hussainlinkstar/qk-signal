// SIGV2-1219: the gate's own contract.
//
// compare-to-design.sh once exited 0 having compared nothing: an apostrophe
// in a comment closed the single-quoted `bash -lc` script, the container was
// handed only the part before it, and the run ended after `next build` with
// no report and a success status. Nobody noticed, because a green gate looks
// the same whether it checked everything or nothing.
//
// These tests hold the line that made that possible: the launcher must fail
// when the run leaves no fresh report behind. `docker` is replaced with a
// stand-in via SIGV2_DOCKER, so this costs milliseconds and no container.
//
// node:test, not vitest: frontend/vitest.config.ts excludes e2e/**. Run via
// `npm run test:design-shard`, which frontend-ci invokes.
import assert from "node:assert/strict";
import { describe, it, before, after } from "node:test";
import { execFileSync } from "node:child_process";
import { chmodSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, "..", "..");
const LAUNCHER = join(FRONTEND, "e2e", "visual", "compare-to-design.sh");
const REPORT_DIR = join(FRONTEND, "e2e", "design-comparison", "report");

// A stand-in for `docker` that behaves like the truncated container did:
// every invocation succeeds and nothing is produced.
const FAKE_DOCKER_OK = `#!/usr/bin/env bash
exit 0
`;

// The same, except the run writes the report the real one would.
const fakeDockerWritingReport = (reportDir) => `#!/usr/bin/env bash
if [ "\${1:-}" = "run" ]; then
  mkdir -p '${reportDir}'
  printf '{}\\n' > '${reportDir}/report.json'
  printf '# report\\n' > '${reportDir}/report.md'
fi
exit 0
`;

let workdir;
let designDir;

const writeFakeDocker = (name, body) => {
  const path = join(workdir, name);
  writeFileSync(path, body);
  chmodSync(path, 0o755);
  return path;
};

// The launcher is a gate: a non-zero exit is the expected outcome in most of
// these tests, so the status and the output are both returned rather than
// thrown.
const runLauncher = (dockerPath, args = []) => {
  try {
    const stdout = execFileSync("bash", [LAUNCHER, ...args], {
      cwd: FRONTEND,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, SIGV2_DOCKER: dockerPath, DESIGN_DIR: designDir },
    });
    return { status: 0, output: stdout };
  } catch (err) {
    return { status: err.status ?? 1, output: `${err.stdout ?? ""}${err.stderr ?? ""}` };
  }
};

describe("compare-to-design.sh cannot pass without a report", () => {
  before(() => {
    workdir = mkdtempSync(join(tmpdir(), "sigv2-harness-"));
    // The launcher refuses to start without a mockup directory; its contents
    // do not matter here, because the stand-in never reads them.
    designDir = join(workdir, "mockup");
    mkdirSync(designDir);
  });

  after(() => {
    rmSync(workdir, { recursive: true, force: true });
    rmSync(REPORT_DIR, { recursive: true, force: true });
  });

  it("fails when the run exits 0 without writing a report", () => {
    const { status, output } = runLauncher(writeFakeDocker("docker-silent", FAKE_DOCKER_OK));
    assert.equal(status, 1, "a run that compared nothing must not exit 0");
    assert.match(output, /report\.json after the run/);
  });

  it("fails when only a stale report from an earlier run is on disk", () => {
    // Written BEFORE the launcher starts, so it cannot be this run's answer.
    // The launcher clears the directory first and the timestamp floor backs
    // that up, so either defence may be the one that speaks.
    mkdirSync(REPORT_DIR, { recursive: true });
    writeFileSync(join(REPORT_DIR, "report.json"), "{}\n");
    writeFileSync(join(REPORT_DIR, "report.md"), "# stale\n");
    // A stand-in that leaves the directory exactly as it found it.
    const { status, output } = runLauncher(writeFakeDocker("docker-stale", FAKE_DOCKER_OK));
    assert.equal(status, 1, "a leftover report must not be read as this run's answer");
    assert.match(output, /report\.json after the run|predates this run/);
  });

  it("passes when the run writes a fresh report", () => {
    const { status } = runLauncher(
      writeFakeDocker("docker-ok", fakeDockerWritingReport(REPORT_DIR))
    );
    assert.equal(status, 0);
  });

  it("reports the container's own failure status when a report was written", () => {
    const failing = fakeDockerWritingReport(REPORT_DIR).replace("exit 0\n", "exit 3\n");
    const { status } = runLauncher(writeFakeDocker("docker-fail", failing));
    assert.equal(status, 3, "a real comparison failure must reach the caller unchanged");
  });
});
