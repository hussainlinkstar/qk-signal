#!/usr/bin/env node

import { spawn } from "node:child_process";
import os from "node:os";

const isWsl =
  process.platform === "linux" &&
  (Boolean(process.env.WSL_DISTRO_NAME) || os.release().toLowerCase().includes("microsoft"));

const tempCandidates = [process.env.TMPDIR, process.env.TMP, process.env.TEMP, os.tmpdir()].filter(
  (value) => typeof value === "string" && value.trim().length > 0
);
const usesWindowsMountedTemp = tempCandidates.some((value) => /^\/mnt\/[a-z](\/|$)/i.test(value));

if (isWsl && usesWindowsMountedTemp) {
  process.env.TMPDIR = "/tmp";
  process.env.TMP = "/tmp";
  process.env.TEMP = "/tmp";
}

const command = process.platform === "win32" ? "npx.cmd" : "npx";
const child = spawn(command, ["vitest", "run", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: process.env,
});

child.on("error", (error) => {
  console.error(error);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
