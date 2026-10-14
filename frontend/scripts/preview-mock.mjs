#!/usr/bin/env node
/**
 * Build (optional) + run Next production server against e2e/visual/stub-backend.mjs.
 *
 * Usage:
 *   node scripts/preview-mock.mjs           # start stub + next (expects existing build)
 *   node scripts/preview-mock.mjs --build   # npm run build first, then start
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const shouldBuild = process.argv.includes("--build");

const NEXT_PORT = process.env.PORT || "3000";
const STUB_PORT = process.env.STUB_PORT || "8000";

function run(command, args, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: frontendRoot,
      env: { ...process.env, ...env },
      stdio: "inherit",
      shell: process.platform === "win32",
    });
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} ${args.join(" ")} exited ${code}`));
    });
  });
}

function start(command, args, env = {}) {
  return spawn(command, args, {
    cwd: frontendRoot,
    env: { ...process.env, ...env },
    stdio: "inherit",
    shell: process.platform === "win32",
  });
}

async function main() {
  if (shouldBuild) {
    console.log("Building frontend (NEXT_PUBLIC_ENABLE_RTL=true)...");
    await run(
      "node",
      ["scripts/next-with-env.mjs", "NEXT_PUBLIC_ENABLE_RTL=true", "NEXT_TELEMETRY_DISABLED=1", "build"]
    );
  }

  console.log(`Starting stub backend on :${STUB_PORT}...`);
  const stub = start("node", ["e2e/visual/stub-backend.mjs"], {
    PORT: STUB_PORT,
  });

  await new Promise((r) => setTimeout(r, 800));

  console.log(`Starting Next on :${NEXT_PORT} (BACKEND_URL=http://127.0.0.1:${STUB_PORT})...`);
  console.log(`Open http://127.0.0.1:${NEXT_PORT}/mock-signin then /dashboard/audit/2`);
  const next = start("npx", ["next", "start", "-p", NEXT_PORT], {
    NEXT_DIST_DIR: ".next-build",
    BACKEND_URL: `http://127.0.0.1:${STUB_PORT}`,
    MOCK_PREVIEW: "1",
    NEXT_TELEMETRY_DISABLED: "1",
    PORT: NEXT_PORT,
  });

  const shutdown = () => {
    stub.kill("SIGTERM");
    next.kill("SIGTERM");
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  next.on("exit", (code) => {
    stub.kill("SIGTERM");
    process.exit(code ?? 1);
  });
  stub.on("exit", (code) => {
    if (code && code !== 0) {
      console.error(`stub exited ${code}`);
      next.kill("SIGTERM");
      process.exit(code);
    }
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
