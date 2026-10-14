# Playwright E2E Suite

## Run

```bash
cd frontend
npm run test:e2e
```

## Environment Variables

- `E2E_BASE_URL`: app URL (default: `http://localhost:3000`)
- `E2E_AUDIT_URL`: target URL used by audit tests (default: `https://pixelartisan.agency`)
- `E2E_AUDIT_TIMEOUT_MS`: max wait for async audit completion (default: `720000`)
- `E2E_EXPECT_GUEST_RATE_LIMIT`: set to `true` to require a `429` on repeated guest audits
- `E2E_WEB_SERVER_CMD`: optional command to auto-start the app before tests

## Coverage

- User registration + login + session bootstrapping
- Authenticated fast audit with credit deduction and payload-to-UI checks
- Guest audit with locked report assertions and rate-limit behavior
- Invalid URL validation guard
- MFA enable + MFA login challenge

## Visual regression (SIGV2-1045)

The functional projects above assert behaviour. The `visual-*` projects assert
pixels: a page is accepted only when the rendered output is pixel-identical to
an approved baseline. Baselines are generated and compared **only** inside the
pinned image `mcr.microsoft.com/playwright:v1.58.2-jammy`, locally and in CI,
so font rasterisation is identical in both. Never commit a baseline rendered
on macOS or in any other environment - it will fail in CI on font metrics
alone.

The image is pinned by digest, not just tag
(`v1.58.2-jammy@sha256:4698a737...`), in both `ci.yml` and
`e2e/visual/run-in-docker.sh`, because the tag is mutable and a retagged
image would silently change the toolchain that produces and compares
baselines. The digest is part of the baseline contract: changing the image
means re-recording all baselines, reviewed, never a silent refresh.

The pixel budget is zero (`maxDiffPixels: 0`), with `threshold: 0.004`
for one-unit colour rounding. Larger differences are either a defect or an
explicitly recorded, approved correction. Never widen the tolerance or refresh
a baseline merely to make CI pass.

### Projects

- `visual-1440x900-en`, `visual-1440x1100-en`, `visual-1440x900-ar`,
  `visual-1440x1100-ar`
- Desktop Chrome, `deviceScaleFactor: 1`, light colour scheme, reduced motion.
- Locale is selected with the `preferred_language` cookie (`en`/`ar`). Arabic
  requires `NEXT_PUBLIC_ENABLE_RTL=true` at build time; the visual fixture
  asserts `document.documentElement.dir` so an Arabic baseline that silently
  rendered LTR cannot be recorded.
- A green `*-ar` baseline proves direction and mirrored layout only, never
  translation. A page with no `ar` strings still passes its AR project: it
  renders English copy inside an RTL container, which is exactly what it
  should be caught for. Do not read an AR baseline as evidence a page is
  translated.

### Running

```bash
npm run test:e2e:visual          # compare against committed baselines
npm run test:e2e:visual:update   # record baselines (local, deliberate only)
```

Both scripts run the whole flow inside the pinned image via Docker, including
the production build itself (`NEXT_PUBLIC_ENABLE_RTL=true npm run build`,
then `next start`), so a baseline is never produced from a host-built app.
No host-side build step is needed; named Docker volumes cache `node_modules`,
`.next-build` and the npm cache between runs.
`test:e2e:visual:update` exists for deliberate baseline recording only and is
not reachable from CI - the CI job never passes `--update-snapshots`.

### Trap: the Docker volumes are per checkout (SIGV2-1138)

Both Docker-hosted suites cache `node_modules`, the npm cache and
`.next-build` in named volumes. Those names used to be global constants
(`sigv2-visual-node-modules`, `sigv2-visual-next-build`,
`sigv2-visual-npm-cache`), so two checkouts running a suite at the same time
shared one set of mutable state. Every symptom of that collision looks like a
defect in the branch under test, which is the worst kind of false signal, and
all of these were really observed:

- `Another next build process is already running` - two `next build`
  invocations against one `.next-build`.
- `Cannot find module playwright-core` with 28 phantom test failures - two
  `npm ci` invocations tearing down and repopulating one `node_modules`.
- One run removing the other's container while cleaning up.
- A full design-compare reporting `RENDER_FAILED` on six screens that pass
  when run scoped.

`e2e/visual/docker-scope.sh` now derives the volume names from the absolute
repo root, so every worktree (and the main clone) gets its own warm cache and
cannot touch anyone else's:

```
sigv2-visual-<checkout>-<checksum>-node-modules
sigv2-visual-<checkout>-<checksum>-next-build
sigv2-visual-<checkout>-<checksum>-npm-cache
```

Within one checkout the two suites still share those volumes on purpose: they
build the same app from the same lockfile. Running both at once in one
checkout is therefore made impossible rather than corrupting - the container
name is scoped too and `docker run --name` refuses a duplicate, so the second
run exits immediately with an explanation. Set `SIGV2_VOLUME_SCOPE` to give a
run its own isolated set of volumes (for a deliberate second concurrent run in
the same checkout, or to reuse a cache after moving a checkout); a cold scope
pays one `npm ci` and one full build.

`docker volume ls | grep sigv2-visual` lists them. Removing one only costs the
next run in that checkout its warm cache.

### Fonts: local assets at build time and runtime

Inter, Roboto Mono, Geist, Geist Mono and Satoshi are committed WOFF2 assets,
loaded through `next/font/local`. Both cold builds and runtime rendering use
local files: no Google font stylesheet or font download is needed. Sources,
versions, SHA-256 hashes and licenses for the four migrated families are in
`src/app/fonts/font-sources.json` (SIGV2-1179).

The fixture still fails any request to an external font host and checks that
the self-hosted dashboard families are present before screenshots. Keep these
checks and the pinned Playwright image; never refresh baselines to hide a font
change.

The per-checkout `.next-build` volume and CI's `.next-build/cache` cache speed
up compilation. They are performance optimizations; build correctness must
not depend on a warm cache. With dependencies installed, a fresh Next output
and `docker run --network none`, `npm run build` must exit 0.

### Adding a page to the visual set

Create `e2e/visual/<feature>.visual.spec.ts`:

```ts
import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

visualTest.describe("my page", () => {
  visualTest("default state", async ({ page }) => {
    await gotoAndSettle(page, "/my-route");
    await expect(page).toHaveScreenshot("my-page.png", { fullPage: true });
  });
});
```

`visualTest` (in `e2e/visual/visual-fixtures.ts`) does the determinism work
for you: a fixed clock and seeded `Math.random`, a stylesheet disabling
animation/transition/caret/scrollbars, `document.fonts.ready`, a check that
the self-hosted families (Inter, Roboto Mono, Satoshi) actually loaded, the
`dir` assertion above, and a hard failure if any request goes to an external
font host. It offers no masking API on purpose.

It also pre-sets cookie consent to a persisted "accept all" record (the real
localStorage record and cookie that `src/lib/cookieConsent.ts` writes), so
the consent banner does not render. That is the approved default: the MVP
captures show no banner because consent is reached only through the footer's
"Cookie settings" link. To photograph the banner itself, opt in with
`visualTest.use({ cookieConsent: "unset" })` in a dedicated spec -
`e2e/visual/cookie-consent.visual.spec.ts` is the example, and the only place
the banner is covered.

A mask is only ever permitted for content that is genuinely nondeterministic,
must be listed with a written reason in the spec, and may never cover layout
or a component under test. If you reach for a mask to make a diff pass, the
diff is telling you something real - stop and find out what.

Any fixture data a spec introduces must be obviously synthetic and labelled
as such. Do not fabricate plausible-looking product data.

### How a baseline is reviewed and updated

1. Record locally with `npm run test:e2e:visual:update` inside the pinned
   image. Commit the `e2e/visual/**/*-snapshots/` PNGs with the story.
2. The reviewer of the PR is the reviewer of the baseline: look at the PNGs,
   not just the green check.
3. When a later diff fails, CI uploads `test-results/` (expected / actual /
   diff images) as the `visual-regression-diffs` artifact. A failure means the
   rendered page changed. Either it is a defect - fix the page - or it is an
   intentional visual change, which Razvan approves explicitly before the new
   baseline is recorded.
4. A stakeholder-approved copy correction is never folded into a rebaseline:
   record the approval (ticket reference and Razvan's sign-off) in the commit
   that updates the baseline, so the image change and the approval travel
   together.

## Design-vs-build comparison (SIGV2-1066, gated by SIGV2-1115)

The `visual-*` suite above is a regression harness: its baselines are
pictures of our own build and cannot detect divergence from the approved
design. The acceptance gate (Gate 1 criterion 3) compares each built screen
against the approved MVP pages instead:

```bash
npm run test:design-compare              # compare + gate against the committed references
npm run test:design-compare:update       # re-record the design reference set
npm run test:design-compare:thresholds   # re-seed thresholds.json from a measured run
npm run test:design-compare:ci           # what CI runs (--reference-only, no mockups needed)
```

The full MVP comparison runs in GitHub only on explicit manual CI dispatch with
`design_comparison=true` (default false). It does not repeat automatically on
preprod promotion. Frontend development PRs still run blocking visual regression.
Promotions can reuse recent successful CI evidence for identical content and
verification policy; missing evidence runs the ordinary gates.

`e2e/visual/compare-to-design.sh` runs inside the same pinned image and
mounts the approved mockups (`Qiko-Signal-MVP-TBR/mockup`, override with
`DESIGN_DIR`) read-only at `/design`, served by
`e2e/design-comparison/serve-design.mjs`. `compare.mjs` renders every
approved page at 1440x900 and 1440x1100, EN and AR (the mockup's own
`qiko-lang`/`applyLang` mechanism), renders the built counterpart on the same
stub backend as the visual suite, and emits a difference percentage, a diff
image and a PASS/FAIL verdict per variant.

### Trap: `DESIGN_DIR` from a git worktree (SIGV2-1138)

The approved mockups live outside this repo, next to the **main clone**. The
default used to be `$REPO_ROOT/../Qiko-Signal-MVP-TBR/mockup`, which does not
exist from a worktree under `.devin/worktrees/<key>/`: the script exited 1 and
anyone working in a worktree silently could not run the gating suite at all.
It now tries, in order, `$DESIGN_DIR` if set, the sibling of this checkout,
then the sibling of the main worktree (`git worktree list --porcelain` reports
the main one first by definition), and names every path it tried when none
exists. Passing `DESIGN_DIR` explicitly still wins, and still works.

- The design renders are the reference set, committed under
  `e2e/design-reference/` with `manifest.json` recording each source filename
  and a SHA-256 of the source HTML. A design change surfaces as a hash
  mismatch (`DESIGN_CHANGED`) - a visible, reviewable event.
- The manifest also records a SHA-256 of each **shared** design asset
  (`SHARED_DESIGN_ASSETS` in `screens.mjs`: `signal.css` and `app.js`).
  SIGV2-1138: hashing only each screen's own HTML left a hole. Every approved
  page pulls the same stylesheet, and `app.js` is what injects the sidebar and
  nav into all of them, so a change to either invalidates every reference PNG
  in the set - and nothing would have said so. A drift is now a
  `DESIGN_CHANGED` failure like any other. A reference recorded before the
  shared hashes existed also fails: nothing can prove it was rendered against
  the current stylesheet. The check is local-only, like the source-HTML check,
  because `--reference-only` has no mockups to hash.
- Exclusion regions (fixture data, chart rasterisation) are named per screen,
  masked on BOTH renders before diffing, and printed with their justification
  into the run's `report.md`. They are never widened to make a screen pass.
- The run writes `report/` (report.md, report.json, built renders, diff
  images). It is **git-ignored on purpose**: a report is true only for the
  commit that produced it, and ours went stale twice inside two hours. Attach
  a run's output to the owning ticket as evidence rather than committing it,
  and regenerate before trusting any figure.
- A percentage is only as honest as its masks. Where an exclusion covers a
  whole content region rather than the individual non-deterministic values
  inside it, the surrounding frame can misalign and the number then measures
  mask geometry instead of design divergence. The AIO and SEO drilldowns are
  currently in that state, so treat their figures as unusable until the masks
  are tightened (SIGV2-1066). Read the diff image before quoting any number.

### Full-page capture (SIGV2-1115)

Both sides are captured with `fullPage: true`. Until SIGV2-1115 the harness
photographed the first viewport only: on the dashboard that was roughly 39%
of the page, so anything below the fold could diverge unnoticed, and a screen
could sit at 2% while most of it had never been looked at.

The two documents are rarely the same height, and pixelmatch needs identical
dimensions, so the diff is computed over the **union canvas**: pixelmatch
across the overlapping region, plus every pixel outside the overlap counted
as divergent outright. Padding one side with a fill colour was rejected - if
the fill ever matched the other side's content the harness would under-count
in silence. A build that is 800px shorter than its approved design IS
divergent and the number now says so. `report.json` records `designSize`,
`builtSize`, `heightDelta`, `overlapDiffPixels` and `nonOverlapPixels` per
variant, so you can always tell a height mismatch from a content mismatch.

Exclusion rectangles are collected in document coordinates
(`getBoundingClientRect()` plus `window.scroll{X,Y}`), because a full-page
screenshot is the document, not the viewport.

The run uses one Chromium per screen, per viewport, per locale rather than one
for the whole run. Full-page captures of the taller screens grow the browser's
memory enough that later screens start timing out on their ready selector and
report a failure they do not deserve; that was observed (billing, fixes,
settings and workspace-settings all failed in sequence, all four passed on
their own). Per-tab capture multiplies the captures taken from one page load,
so SIGV2-1138 recycles the browser more often than before, not less.

Both renders wait for quiescence before the screenshot: the page must hold
the same layout signature (scroll height plus rendered text length, so a
payload that swaps content without changing height is caught too) for eight
consecutive 250ms samples, with a 30s budget and a warning if it never
settles. `networkidle` alone was not enough; several screens land an async
payload after it, and a full-page capture taken while a loading skeleton is
still on screen is a different picture every run.

### Per-tab capture (SIGV2-1138)

A tabbed screen used to be photographed in its default tab only, and the two
drilldowns additionally masked their tab panels, so **work inside a
non-default tab was invisible to this gate in both directions**: it could not
confirm an alignment and it could not catch a regression. Two measured
instances, both honestly recorded at the time as unverifiable rather than
having a budget fudged:

- the My Profile Data tab was rebuilt to the approved design and the figure
  did not move at all, 24.04 before and after, because the capture showed the
  Profile tab on both sides;
- prompt creation was moved onto the approved AIO Prompts tab and the AIO
  detail figure was byte-identical, 16.62 both times.

A screen in `screens.mjs` can now declare `tabs`, and each entry becomes its
own comparison screen:

```js
tabs: [
  {
    id: "data",            // the mockup's data-tab value
    buildTab: "data",      // optional; the build's SignalTabs id if it differs
    captures: "Data: the export, retention and account-deletion rights.",
    exclusions: [...],     // optional; defaults to the base screen's set
  },
],
```

- Its id is `<screen>-tab-<tab>`, which names its reference PNGs, its manifest
  entries and its own `thresholds.json` budget. A per-tab screen with no
  budget fails `NO_THRESHOLD` exactly like any other screen: a new tab is
  never a free pass.
- The tab is activated on **both** sides before the capture: the mockup's own
  `#tabs button[data-tab=X]` -> `.panelw[data-panel=X].on` mechanism, and the
  build's `#signal-tab-X` -> `#signal-tabpanel-X` (every tabbed screen in the
  app goes through `components/signal/SignalTabs`). Both waits are on the
  panel appearing, not a sleep, so a catalogue entry naming a tab that does
  not exist fails loudly (`DESIGN_STATE_FAILED` / `RENDER_FAILED`) instead of
  quietly photographing the default tab again.
- Tab ids are not always the same on the two sides: Workspace Settings calls
  them `general`/`team`/`client`/`whitelabel`/`developer` in the design and
  `workspace-overview`/`workspace-team`/... in the build. `buildTab` (and
  `designTab`) exist for exactly that.
- All states of one screen share a single page load per viewport and locale,
  so a tab costs a settle plus a screenshot rather than another navigation.
- The default tab is listed only where the base screen's exclusions mask the
  panel content (`aio-detail`, `seo-detail`). Everywhere else the base entry
  already compares the default tab unmasked, and listing it again would record
  four identical reference PNGs for nothing.
- The per-tab screens of the two drilldowns deliberately do **not** inherit
  the base `fixture-elements` exclusion: it masks `[role='tabpanel']`
  children, which is precisely what a per-tab capture exists to compare. They
  keep only the hero gauge, the tab count badges, the target-bearing section
  titles, the no-target deviation and the sidebar switcher. Their figures are
  therefore higher than the base screens' and honestly so.
- `--screens=my-profile` selects a base screen and all of its tab screens;
  `--screens=my-profile-tab-data` selects one tab.
- `--shard=<index>/<count>` runs only one slice of the catalogue: shard
  `<index>` of `<count>` (1-based). It is applied AFTER `--screens`, so both
  are filters and a restricted run shards the restricted set. A malformed
  value exits 1 rather than silently running unsharded. The partition is
  balanced by state count, not group count, because group sizes are very
  uneven (each state costs one capture per viewport per locale).

### Known gap: three screens render differently on a GitHub runner

`audit-start`, `fixes` (English only) and `settings` produce a different
built render in CI than in a local container, with the same image, the same
lockfile and the same stub:

| Screen      | Local built | CI built  |
| ----------- | ----------- | --------- |
| audit-start | 1440x915    | 1440x1582 |
| fixes (en)  | 1440x1111   | 1440x1091 |
| settings    | 1440x2077   | 1440x1999 |

All three are data-driven list screens, so the likely cause is an async
payload that lands differently there, but it is **not** simple timing: the
local figures are reproducible to the hundredth of a percent across runs and
survive wiping the `node_modules` and `.next-build` volumes, and `settings`
flapped between two consecutive CI runs (68.92% then 69.40%). The visual
regression suite runs at zero tolerance in both environments, so font
rasterisation is not the difference.

Until this is understood, those three entries in `thresholds.json` carry a
`ciMeasured` block alongside `measured`, the budget is the **maximum of the
two environments**, and `ciMeasuredNote` records what is unexplained.
`--write-thresholds` preserves `ciMeasured` and keeps taking the max, so a
local re-record cannot quietly drop a budget below what CI actually measures.
Those three screens are therefore looser than the other seventeen; that is a
visible, written-down concession, not a silent one. Narrowing them means
finding the environment difference, not editing the number.

### The gate (SIGV2-1115)

Before SIGV2-1115 this harness printed a divergence number and exited 0
whether that number was 1% or 41%, so nothing it measured could ever stop a
change. It now has a verdict:

- `e2e/design-comparison/thresholds.json` holds a per-screen
  `maxDiffPercent`. It is committed, so changing a budget is a reviewable act
  in a diff, not a flag on a command line.
- A variant over its screen's threshold fails and the process exits non-zero.
- Each entry records `measured` (every variant) and `measuredMaxPercent`
  alongside the limit, so a reviewer can see the headroom without rerunning
  anything.
- Thresholds were **seeded from the divergence measured at the time each
  screen was first gated**, rounded up to the next 0.1 percentage point (the
  precision the report quotes). The gate therefore started green and
  ratchets: its job is to stop things getting worse while the known gaps are
  worked through, not to pretend they are already closed.
- **Lowering a value is ordinary progress. Raising one to make a failing
  screen pass is not an acceptable fix.** A failure means the build moved
  away from the approved design: fix the build, or get the design change
  approved and re-record the reference set.
- A screen with no entry in `thresholds.json` **fails**. A missing screen is
  never a pass.
- Reference problems fail too, each with its own reason: `MISSING_REFERENCE`,
  `DESIGN_CHANGED` (the approved HTML, or a shared design asset, changed since
  the reference was recorded), `REFERENCE_TAMPERED` (the committed PNG no
  longer matches the SHA-256 in the manifest), `EXCLUSIONS_CHANGED`
  (screens.mjs declares different exclusions than the ones recorded with the
  reference), `RENDER_FAILED` (the built route did not render, or the tab
  could not be opened on the built side), and `DESIGN_STATE_FAILED`
  (SIGV2-1138: the approved page could not be put into the state a catalogue
  entry asks for, i.e. a tab that does not exist). `RENDER_FAILED` and
  `DESIGN_STATE_FAILED` are confined to the screen or the tab that caused
  them rather than aborting the run, so one broken route or tab still leaves
  you a full table.

### No silent skips (SIGV2-1115)

Ten of the 21 catalogued screens carried `status: "not-implemented"` and were
skipped without a word. All ten were in fact built: developer-hub,
audit-start, audit-run, billing, billing-success, billing-cancel,
billing-history, gate, my-profile and reports. Every one of those routes
resolves to a real page under `src/app` and renders. They are now compared
like any other screen.

They carry no exclusions, deliberately: their figures are raw and unmasked,
so nothing about them is hidden to make a number look better. Several of them
are a long way from their approved design, and the recorded thresholds say so
plainly. Closing that distance is the work the ratchet exists to drive.

`status: "not-implemented"` is now a **hard failure** of the run. The only
sanctioned way to not compare an approved page is `EXCLUDED_DESIGNS` in
`screens.mjs` - one list, each entry with its reason, printed into every
report.

### CI

`.github/workflows/ci.yml` shares one Node 24 build and the pinned Playwright
image between both browser suites. Visual regression remains **blocking on
frontend PRs**. The full MVP comparison is **blocking on every PR targeting
`preprod`**, including backend-only promotions, and is available on manual CI
runs. Ordinary PRs targeting `main` run visual regression without the full MVP
comparison. A production promotion inherits the content already verified on
preprod; it does not force another MVP comparison for an unchanged frontend.

`CI Status` requires successful change detection and security scanning, plus
every application/browser job selected for that run. A required job reporting
`skipped`, `failure`, or `cancelled` fails the aggregate. GitHub branch rules
must separately require `CI Status`; declaring the job does not enforce merging.

To compare a design change before promotion, run CI manually with the full
comparison enabled (the default):

```bash
gh workflow run ci.yml --ref <branch> -f design_comparison=true
```

Manual runs execute both application suites, visual regression and security;
setting `design_comparison=false` omits only the full MVP comparison. The commit
identity gate also checks manual branches against the default branch. Manual CI
does not deploy anything. A comparison only starts when the app is ready and
the run has not been cancelled; reports are still published after test failures.

CI runs `--reference-only`. The approved mockups live outside this repo and a
CI checkout does not have them, so CI compares against the committed
reference PNGs plus the design-side exclusion geometry recorded in
`manifest.json` when the references were last recorded. Two consequences
worth knowing:

- The source-HTML hash check (`DESIGN_CHANGED`) only runs locally, where the
  mockups are mounted. CI cannot see a change to the approved design.
- The committed PNGs are checked against their recorded SHA-256 instead, so a
  reference edited without re-recording fails in CI as `REFERENCE_TAMPERED`.

CI compares the entire catalogue in one pass and uploads one
`design-comparison-report` artifact plus the divergence table in the job
summary. It does not repeat dependency installation and the build per shard.
The harness still supports `--shard=<i>/<n>` for explicit local runs; the
partition is computed from the catalogue and checked by `assertPartition`.
Any future parallelization must use separate output directories and verify
complete, non-duplicated catalogue coverage before reporting success.

### Parity reference

The 46 desktop captures in
`Qiko-Signal-MVP-TBR/review-screenshots/implementation-reference` are the
approved mockup parity reference for the SIGV2-1033..1042 stories, mapped to
tickets through that folder's `manifest.json` (`screenshot_sha256` fields).
The three captures marked `diagnostic_only: true` (mobile) are excluded from
pixel comparison because the static prototype itself overflows horizontally -
they inform layout work only.

Do not confuse the two kinds of baseline: the mockup captures are the _design
target_ each story implements; the `*-snapshots/` PNGs recorded by this suite
are the _regression reference_ that later changes are held against.

Concrete example: the current `/maintenance` page is a dark standalone
"We'll be right back" screen, while the approved MVP maintenance design
(`SIGV2-1033--maintenance--default--en.png` in the parity folder) is the full
app shell with a light "Scheduled maintenance" card. The exemplar baselines
in this suite therefore pin _today's_ page as a regression reference;
SIGV2-1033 will re-record them when it implements the approved design.
