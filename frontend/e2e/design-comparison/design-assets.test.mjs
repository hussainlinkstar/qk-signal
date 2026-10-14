import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const moduleUrl = new URL("./design-assets.mjs", import.meta.url);

test("design references pin both shared and screen-specific assets", async () => {
  assert.ok(existsSync(moduleUrl), "screen-specific asset hashing must exist");
  const { hashDesignAssets } = await import(moduleUrl.href);
  const root = mkdtempSync(join(tmpdir(), "signal-design-assets-"));
  try {
    writeFileSync(join(root, "signal.css"), "body{}");
    writeFileSync(join(root, "prompt-setup.js"), "version1");
    const before = hashDesignAssets(root, ["signal.css", "prompt-setup.js"]);
    assert.equal(before["prompt-setup.js"], createHash("sha256").update("version1").digest("hex"));
    writeFileSync(join(root, "prompt-setup.js"), "version2");
    const after = hashDesignAssets(root, ["signal.css", "prompt-setup.js"]);
    assert.equal(before["signal.css"], after["signal.css"]);
    assert.notEqual(before["prompt-setup.js"], after["prompt-setup.js"]);
    assert.throws(() => hashDesignAssets(root, ["missing.js"]));
    assert.throws(() => hashDesignAssets(root, ["../outside.js"]));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
