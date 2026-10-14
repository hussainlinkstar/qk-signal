# Qiko Signal — Verbatim MVP UI Rewrite Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace ALL of the Signal (non-admin) frontend UI/UX with the `signal-MVP` design **verbatim** — port `signal.css` as the styling source of truth and rebuild every page's markup 1:1 from the corresponding `signal-MVP/*.html`, wired to the existing backend. Only `/admin/**` keeps its current UI.

**Architecture:** Port `signal.css` into the app as a **scoped** global stylesheet (every rule under a `.sg` root class) so it never touches `/admin`. Wrap the dashboard page-content area in `<div className="sg">`. Each Signal page becomes a React component that renders the exact MVP HTML class structure (`.hero`, `.sec`, `.card`, `.act`, `.kpis`, `.spanel`, `.eng`, `.wsec`, `.fstat`, `.gate`, …) with real backend data bound in and honest connect/empty states where a source isn't connected. Keep the existing `SignalAppShell` sidebar (already MVP-derived) but restyle its inner markup to the MVP `.side/.nav/.switch` classes.

**Tech Stack:** Next.js 15 App Router, TypeScript, React, plain CSS (ported `signal.css`), existing services/hooks in `frontend/src/services` + `frontend/src/hooks`.

## Global Constraints

- **Do NOT touch `/admin/**`** (any file under `frontend/src/app/(app)/admin` or admin-only components). Admin keeps its current UI entirely.
- **Do NOT delete or change backend behaviour.** Frontend-only rewrite. Wire to existing endpoints/services/hooks.
- **No feature loss.** Every capability reachable today (run audit, prompt.AI, Jira export, competitors, monitoring, tasks, agents, billing, white-label, developer API keys, onboarding, create project) must remain reachable in the new UI.
- **Two pillars only:** SEO + AIO (AIO = AEO+GEO combined). Never render a third pillar.
- **MVP fidelity:** classes/markup/spacing/typography copied from `signal-MVP/*.html` + `signal.css` verbatim. Source files: `/Users/user/signal-MVP/`.
- **Colors/tokens** come from the ported CSS variables (`--ink,--paper,--panel,--t-1..3,--line,--blue,--purple,--grad,--good/warn/bad,--mono,--disp,--body`). Do not reintroduce Tailwind `--primary/--accent` glass styling on Signal pages.
- **Verify every task:** `npm run lint` (0 errors) + `npm run build` pass before commit. Commit per task. Push to `main` (auto-deploys).

---

## File Structure

- Create `frontend/src/styles/signal-mvp.css` — the ported `signal.css`, every selector scoped under `.sg`.
- Modify `frontend/src/app/(app)/dashboard/DashboardLayoutClient.tsx` — import the stylesheet; wrap page content `<main>` in `<div className="sg">`; ensure `SignalAppShell` inner markup uses MVP `.side/.nav/.switch/.foot` classes.
- Rebuild (one file each), using the mapped MVP HTML:

| Route (file) | MVP source | Key MVP sections |
|---|---|---|
| `dashboard/overview/page.tsx` | `Signal Workspace Overview.html` | project cards grid + Add Project (`.switch`/`.modal`) |
| `projects/[projectId]/page.tsx` | `Signal Overview.html` | `.top` · `.dhead` · Traffic KPIs (`.kpis`) · channel mix · two `.spanel` · AIO feeds · engines · Prioritised fixes (`.lockwrap`) |
| `projects/[projectId]/aeo/page.tsx` | `Signal AIO Detail.html` | `.hero` · `.tabs` · `.act` improve · `.st` search types · `.eng` engines · prompts `table` · levers `.setgrid` |
| `projects/[projectId]/seo/ProjectSeoClient.tsx` | `Signal SEO Detail.html` | `.hero` · `.tabs` · `.act` · `.st` factors · keywords `table` · pages `table` |
| `projects/[projectId]/competitive/*` | `Signal Competitors.html` | rank hero · `.seg` chart · leaderboard `table` · head-to-head |
| `projects/[projectId]/settings/page.tsx` | `Signal Settings.html` | `.tabs` product/brand · `.setgrid` · `.range-track` · `.comp` chips · `.conn` |
| `projects/[projectId]/automations/*` | `Signal Agents.html` | `.gate` lock · `.connect` flow · working-now list |
| `projects/[projectId]/monitoring/*` | (reuse AIO/SEO patterns) | `.sec` + `.card` + `table` |
| `projects/[projectId]/tasks/*` | (reuse) | `.card` + `.act`-style task rows |
| `projects/[projectId]/entities/*` | (reuse) | `.card` + `.st` rows |
| `dashboard/connections/page.tsx` | `Signal Data Feed.html` | `.connect`/`.connbar` · sources `.conn` |
| `dashboard/settings/*` | `Signal Workspace Settings.html` | `.pagehead` · `.wsec` tabs · `.wtable` team · `.wupload` · white-label |
| `dashboard/account-settings/page.tsx` | `Signal My Profile.html` | `.pagehead` · `.wsec` Profile/Security/Notifications/Branding/Data |
| `dashboard/billing/page.tsx` | `Signal Billing.html` | `.pagehead` · `.fstat` · usage · plans · invoices `.wtable` |
| `dashboard/developer/page.tsx` | `Signal Developer Hub.html` | `.pagehead` · `.fstat` · quick-start · API reference (dark `--ink` block) |

---

## Task 1: Port signal.css scoped under `.sg`

**Files:** Create `frontend/src/styles/signal-mvp.css`; Modify `DashboardLayoutClient.tsx`.

- [ ] **Step 1:** Copy `/Users/user/signal-MVP/signal.css` verbatim into `signal-mvp.css`. Keep `:root{…}` variables at top (global, harmless). Scope every visual selector under `.sg` using native CSS nesting: wrap the body of the file (everything after `:root` and the `*{box-sizing}`/`html,body{margin:0}` resets — keep those global) in `.sg { … }`, converting top-level selectors to nested (`.card` → `& .card`, `.btn` → `& .btn`, bare `table` → `& table`, `input[type=range]` → `& input[type=range]`, `.hero::before` → `& .hero::before`, `body[data-scope="workspace"] .top` → `&[data-scope-workspace] .top` handled per-page via a wrapper class). Drop the `body{background;color;font}` rule (dashboard already light); instead apply `background/color/font` on `.sg`.
- [ ] **Step 2:** In `DashboardLayoutClient.tsx` add `import "@/styles/signal-mvp.css";` and change the page `<main>` to `<main className="sg relative z-10 flex-1 …">` (add `sg`). Verify admin is NOT under this layout (admin uses its own layout) so it's unaffected.
- [ ] **Step 3:** `npm run build`; open `/dashboard` — confirm existing pages still render (unstyled `.sg` classes are inert until pages use them) and `/admin` is visually unchanged.
- [ ] **Step 4:** Commit `feat(frontend): port signal.css scoped under .sg (MVP styling source of truth)`.

## Task 2: Shell markup to MVP `.side/.nav/.switch`

**Files:** `frontend/src/components/signal/SignalAppShell.tsx` (+ switcher slots).

- [ ] Rebuild `SignalAppShell` internals with MVP classes: `.app`→`.side`(`.brand`+`.nav`+`.foot`), nav groups `.nav .lab` + `.nav a`/`.nav a.on`, footer `.switch`. Keep the same props/data. Build + confirm sidebar matches `signal-MVP` sidebars. Commit.

## Tasks 3-15: One page per task

For each page in the File Structure table, in this order — **Overview (project) → AIO → SEO → Workspace Overview → Billing → Workspace Settings → My Profile → Developer Hub → Data feed → Competitors → Settings (project) → Agents → Monitoring/Tasks/Entities**:

- [ ] **Step A:** Open the mapped `signal-MVP/*.html`. Reproduce its exact markup/classes in the React component (replace the entire old body).
- [ ] **Step B:** Identify the existing data hook/service the old page used (keep the same fetching logic) and bind real values into the MVP markup. Where a data source isn't connected, render the MVP layout with an honest connect/empty state (e.g. GA4 "Connect Google Analytics"), never fake numbers.
- [ ] **Step C:** Preserve every action the old page had (run audit, prompt.AI, Jira export, add competitor/keyword/prompt, toggles, uploads, create project) wired to the same handlers, styled as MVP `.btn`/`.btn.pri`/controls.
- [ ] **Step D:** Delete the old JSX + now-unused old-UI imports (GlassCard, ProjectFeatureScaffold, DashboardPageIntro, MetricCircle, etc.) from that file. Do not delete shared components still used by admin.
- [ ] **Step E:** `npm run lint` + `npm run build`; visually diff against the MVP HTML. Fix any stale tests for that page.
- [ ] **Step F:** Commit `feat(frontend): rebuild <page> verbatim from signal-MVP` and push.

## Task 16: Remove dead old-UI components

- [ ] After all pages are migrated, delete Signal-only old-UI components no longer referenced (`ProjectFeatureScaffold`, `DashboardPageIntro`, Signal usages of `GlassCard`) — verify with a repo-wide reference check that nothing under `/admin` imports them before deleting. Build + commit.

## Self-Review / Verification checklist
- [ ] Every route in the table renders its MVP HTML structure 1:1 (side-by-side check).
- [ ] `/admin/**` visually unchanged; no admin file modified.
- [ ] No third pillar anywhere; AIO+SEO only.
- [ ] Every prior feature reachable (audit, prompt.AI, Jira, competitors, monitoring, tasks, agents, billing, white-label, dev keys, onboarding, create project).
- [ ] Real data bound; unconnected sources show MVP connect/empty states.
- [ ] `npm run lint` 0 errors, `npm run build` passes, tests updated/green.
