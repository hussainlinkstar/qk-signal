#!/usr/bin/env node
/**
 * Windows-safe Next runner. Usage:
 *   node scripts/next-with-env.mjs build
 *   node scripts/next-with-env.mjs start -- -p 3000
 *
 * Extra KEY=VALUE pairs before the command are merged into env:
 *   node scripts/next-with-env.mjs NEXT_PUBLIC_ENABLE_RTL=true build
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");

const args = process.argv.slice(2);
// Local/Docker use .next-build so it does not collide with .next-dev.
// Vercel (and most hosts) require the standard .next output directory.
const defaultDistDir = process.env.VERCEL || process.env.VERCEL_ENV ? ".next" : ".next-build";
const env = {
  ...process.env,
  NEXT_DIST_DIR: process.env.NEXT_DIST_DIR || defaultDistDir,
};
const forwarded = [];

for (const arg of args) {
  if (arg === "--") continue;
  const eq = arg.indexOf("=");
  if (eq > 0 && !arg.startsWith("-") && /^[A-Z_][A-Z0-9_]*$/.test(arg.slice(0, eq))) {
    env[arg.slice(0, eq)] = arg.slice(eq + 1);
    continue;
  }
  forwarded.push(arg);
}

const nextArgs = forwarded.length ? forwarded : ["build"];
const child = spawn("npx", ["next", ...nextArgs], {
  cwd: frontendRoot,
  env,
  stdio: "inherit",
  shell: process.platform === "win32",
});

child.on("exit", (code) => process.exit(code ?? 1));
