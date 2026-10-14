import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * SIGV2-1302: the report's components stay on the approved visual language.
 *
 * Every panel on `/dashboard/audit/{id}` is filled by one of these components,
 * and all eight were still carrying the styling that predates the Signal
 * redesign: 95 occurrences of `rounded-4xl`, `shadow-2xl`, `blur-sm`, hover
 * gradient glows, `drop-shadow` and `tracking-[0.2em]`. None of it appears in
 * any approved mockup, and it is why the cards visibly overlapped the
 * disclosure panels they sat inside, which were designed for flat content.
 *
 * This is a file-level guard rather than a render-level one on purpose. The
 * page is in none of the 42 screens the design gate compares, so there is no
 * visual test to catch a regression here, and a per-component render test
 * would only cover the branches it happens to render. Reading the source
 * covers every branch, including the ones only an unusual payload reaches.
 */

const TABS_DIR = join(process.cwd(), "src/components/results/tabs");

// Each pattern, and what is wrong with it, so a future reader does not have to
// guess why their class was rejected.
const FORBIDDEN: { pattern: RegExp; reason: string }[] = [
  { pattern: /\brounded-4xl\b/, reason: "the approved radius is --r" },
  { pattern: /\bshadow-2xl\b/, reason: "approved cards are flat" },
  { pattern: /\bshadow-inner\b/, reason: "approved cards are flat" },
  { pattern: /\bdrop-shadow-\[/, reason: "no glow on a number" },
  { pattern: /\bblur-sm\b/, reason: "hover glow wrappers are not in the design" },
  { pattern: /\bblur-xl\b/, reason: "decorative blurred blobs are not in the design" },
  { pattern: /\bblur-2xl\b/, reason: "decorative blurred blobs are not in the design" },
  { pattern: /\bblur-\[\d/, reason: "decorative blurred blobs are not in the design" },
  { pattern: /\bbg-linear-to-[a-z]+\b/, reason: "panels carry a flat fill" },
  { pattern: /tracking-\[0\.2em\]/, reason: "the design has no 0.2em heading treatment" },

  // SIGV2-1317 ---------------------------------------------------------------
  // Raw palette colours. Every one of these is a dark-theme tint, and this
  // product's panel is white. Measured against #FFFFFF, where WCAG AA body
  // text needs 4.5:1:
  //
  //   emerald-200  1.28:1    amber-300  1.44:1    emerald-300  1.52:1
  //   amber-400    1.67:1    red-300    1.90:1    emerald-400  1.92:1
  //   red-400      2.77:1
  //
  // The approved tokens do not pass for body text either (--good 3.37:1,
  // --warn 2.58:1, --bad 3.91:1), so the rule is not "swap in a token". It is
  // what SignalAlert does: the tone carries the glyph and the rule, the words
  // sit on --t-1 or --t-2, which is 6.52:1.
  {
    pattern:
      /\b(?:text|bg|border|from|to|via)-(?:amber|emerald|rose|red|green|yellow|lime|teal|cyan|sky|indigo|violet|fuchsia|pink)-\d{2,3}\b/,
    reason:
      "raw palette colour: these are dark-theme tints and all of them fail contrast on the white panel. Use --good/--warn/--bad on the glyph and --t-1/--t-2 for the words, or SignalAlert",
  },

  // A card inside a report section. `ReportDisclosure` is already the card,
  // on the approved Scan history anatomy, so anything in here with a panel
  // fill and the approved radius is a second one. The page was reported for
  // being three of these deep.
  {
    pattern: /rounded-\(--r\)[^"'`]*bg-\(--panel\)|bg-\(--panel\)[^"'`]*rounded-\(--r\)/,
    reason:
      "a card inside the section's own card. Content inside a disclosure is blocks divided by .st, not panels",
  },

  // Shouting micro-labels.
  //
  // Narrowed after it fired on correct code, which is worth recording. The
  // first version rejected any 9 or 10px uppercase, and `signal.css` sets
  // `th{font-family:var(--mono);font-size:10px;letter-spacing:.06em;
  // text-transform:uppercase;color:var(--t-3);font-weight:400}`, so the
  // approved table header is exactly that. A guard that fails the design it
  // is guarding is worse than no guard, because the next person deletes it.
  //
  // What is actually wrong is the weight and the tracking: `text-[9px]
  // font-black uppercase tracking-widest` appears in no mockup at any size,
  // and at 9px with 0.1em tracking it is the least readable thing a page can
  // contain. The approved values are 10 to 10.5px, weight 400, 0.06em on a
  // table header and 0.08em on a `.lab`.
  {
    pattern: /\btracking-widest\b|\btracking-wider\b|tracking-\[0\.[3-9]\d*em\]/,
    reason: "the approved tracking is 0.06em on a table header and 0.08em on a label, never wider",
  },
  {
    pattern: /text-\[9px\]/,
    reason: "nothing in the approved design is set at 9px",
  },
  {
    pattern:
      /text-\[(?:9|10|10\.5)px\][^"'`]*\bfont-(?:bold|black|extrabold)\b|\bfont-(?:bold|black|extrabold)\b[^"'`]*text-\[(?:9|10|10\.5)px\]/,
    reason: "micro-labels are weight 400 in the approved design, not bold or black",
  },
];

const sourceFiles = readdirSync(TABS_DIR).filter(
  (name) => name.endsWith(".tsx") && !name.endsWith(".test.tsx")
);

describe("the audit report tabs stay on the approved visual language", () => {
  it("covers every component that fills a panel on the report page", () => {
    // If a tab is added and this list is not, the new one is unguarded.
    expect(sourceFiles.length).toBeGreaterThanOrEqual(8);
  });

  it.each(sourceFiles)("%s carries none of the pre-redesign styling", (name) => {
    const source = readFileSync(join(TABS_DIR, name), "utf8");
    // Comments may name a retired token to explain why it went: the
    // explanation is what stops it being reintroduced.
    const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");

    const found = FORBIDDEN.filter(({ pattern }) => pattern.test(code)).map(
      ({ pattern, reason }) => `${pattern.source} (${reason})`
    );

    expect(found).toEqual([]);
  });
});
