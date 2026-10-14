#!/usr/bin/env node
/** Dev server + visual stub backend (Windows-safe). */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const NEXT_PORT = "3000";
const STUB_PORT = "8000";

const stub = spawn("node", ["e2e/visual/stub-backend.mjs"], {
  cwd: frontendRoot,
  env: { ...process.env, PORT: STUB_PORT },
  stdio: "inherit",
  shell: process.platform === "win32",
});

await new Promise((r) => setTimeout(r, 600));

console.log(`Mock stub :${STUB_PORT} | Next :${NEXT_PORT}`);
console.log(`Open http://127.0.0.1:${NEXT_PORT}/mock-signin`);
console.log(`Then  http://127.0.0.1:${NEXT_PORT}/dashboard/audit/2`);

const next = spawn(
  "node",
  ["scripts/next-with-env.mjs", "NEXT_DIST_DIR=.next-dev", "dev", "--", "-p", NEXT_PORT],
  {
    cwd: frontendRoot,
    env: {
      ...process.env,
      PORT: NEXT_PORT,
      BACKEND_URL: `http://127.0.0.1:${STUB_PORT}`,
      MOCK_PREVIEW: "1",
    },
    stdio: "inherit",
    shell: process.platform === "win32",
  }
);

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
