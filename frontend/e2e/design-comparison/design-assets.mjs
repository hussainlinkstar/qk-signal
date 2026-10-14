import { createHash } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";

export function hashDesignAssets(directory, assets) {
  const root = realpathSync(directory);
  return Object.fromEntries(
    [...new Set(assets)].sort().map((name) => {
      if (isAbsolute(name) || name.split(/[\\/]/).includes("..")) {
        throw new Error(`Design asset must stay inside the mockup directory: ${name}`);
      }
      const path = realpathSync(resolve(root, name));
      const inside = relative(root, path);
      if (inside.startsWith("..") || isAbsolute(inside)) {
        throw new Error(`Design asset escapes the mockup directory: ${name}`);
      }
      return [name, createHash("sha256").update(readFileSync(path)).digest("hex")];
    })
  );
}
