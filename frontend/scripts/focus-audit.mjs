// SIGV2-1217 one-off measurement: how many interactive elements had no
// visible keyboard focus indicator of their own, i.e. how many were relying
// on the globals.css `outline: 2px solid transparent` rule and therefore
// showed nothing at all on a keyboard tab.
//
// Not shipped as a test; run with `node scripts/focus-audit.mjs`.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = "src";
const TAGS = ["a", "button", "input", "select", "textarea"];

const walk = (dir) => {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.tsx$/.test(p)) out.push(p);
  }
  return out;
};

// A focus declaration of the element's own: any Tailwind focus variant, or an
// opt-in to a named treatment that carries one.
const OWN_FOCUS =
  /(?:focus|focus-visible|group-focus-visible|focus-within):|signal-button|field-focus-ring|input-shell/;
// Elements that deliberately draw nothing and let an ancestor shell paint the
// indicator always say so with `outline-none`.
const DELEGATED = /outline-none/;
// A ring/outline/shadow of its own, which the new base outline could double.
const OWN_RING =
  /(?:focus|focus-visible|group-focus-visible):(?:ring|outline|shadow|border)|signal-button|field-focus-ring/;

const files = walk(ROOT).filter((f) => !/\.test\.tsx$/.test(f));

let total = 0;
let bare = 0;
let delegated = 0;
let ownRing = 0;
const byFile = new Map();

for (const file of files) {
  const src = readFileSync(file, "utf8");
  // Opening JSX tags for the five interactive elements, plus anything with an
  // explicit role="button". Self-closing and multi-line tags both included.
  const re = new RegExp(`<(${TAGS.join("|")})(\\s[^>]*?)?/?>`, "gs");
  for (const match of src.matchAll(re)) {
    const attrs = match[2] ?? "";
    // A disabled control is not keyboard focusable, so it cannot rely on a
    // focus indicator. Only unconditional `disabled` counts.
    if (/\sdisabled(\s|$|=\{true\})/.test(attrs)) continue;
    total += 1;
    if (OWN_RING.test(attrs)) ownRing += 1;
    if (OWN_FOCUS.test(attrs)) continue;
    if (DELEGATED.test(attrs)) {
      delegated += 1;
      continue;
    }
    bare += 1;
    byFile.set(file, (byFile.get(file) ?? 0) + 1);
  }
}

// role="button" elements that are not already one of the five tags.
let roleButton = 0;
for (const file of files) {
  const src = readFileSync(file, "utf8");
  for (const match of src.matchAll(
    /<(?!a\b|button\b|input\b|select\b|textarea\b)[A-Za-z][^>]*?>/gs
  )) {
    const tag = match[0];
    if (!/role=["']button["']/.test(tag)) continue;
    roleButton += 1;
    if (!OWN_FOCUS.test(tag) && !DELEGATED.test(tag)) {
      bare += 1;
      byFile.set(file, (byFile.get(file) ?? 0) + 1);
    }
  }
}

console.log(`files scanned:                      ${files.length}`);
console.log(`interactive elements (a/button/input/select/textarea): ${total}`);
console.log(`  role="button" (non-native):       ${roleButton}`);
console.log(`  with a focus ring/outline of own: ${ownRing}`);
console.log(`  delegating to a focus-within shell (outline-none): ${delegated}`);
console.log(`  NO focus indicator at all:        ${bare}`);
console.log("");
console.log("worst files:");
for (const [file, count] of [...byFile].sort((a, b) => b[1] - a[1]).slice(0, 15)) {
  console.log(`  ${String(count).padStart(4)}  ${file}`);
}
