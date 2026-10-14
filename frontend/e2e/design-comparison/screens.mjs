// SIGV2-1066: the approved-design <-> built-screen catalogue.
//
// One row per approved MVP HTML page in Qiko-Signal-MVP-TBR/mockup. `status`
// records whether the screen has been rebuilt under the redesign programme:
//
//   "built"           - a native counterpart exists and is rendered for the
//                       comparison (route + readySelector + optional setup).
//   "not-implemented" - the approved page has no rebuilt counterpart yet.
//                       SIGV2-1115: this is now a HARD FAILURE of the run, not
//                       a silent skip. A design page that genuinely has no
//                       build target belongs in EXCLUDED_DESIGNS below, with
//                       its reason, and nowhere else.
//
// `exclusions` name regions where fixture data or genuinely nondeterministic
// rendering legitimately differs from the approved page. Each entry is a CSS
// selector resolved on that side's own render, plus the reason it is honest.
// An exclusion is never widened to make a screen pass.
//
// SIGV2-1115 also made the capture full-page on both sides, so every row below
// is now compared over the whole scroll height of both documents, not just the
// first viewport.
//
// SIGV2-1138 added `tabs`. A screen with a tab row used to be photographed in
// its default tab only, so work inside any other tab was invisible to this
// gate in BOTH directions: it could not confirm an alignment and it could not
// catch a regression. Two measured instances: the My Profile Data tab was
// rebuilt to the approved design and the figure did not move at all (24.04
// before and after), and prompt creation was moved onto the approved AIO
// Prompts tab and the figure was byte-identical (16.62 both times). Each entry
// in `tabs` becomes its own comparison screen, id `<screen>-tab-<tab>`, with
// its own reference renders and its own budget: the tab is activated on BOTH
// sides before the capture, so the two sides are always showing the same tab.
//
// The default tab is listed only where the base screen's `exclusions` mask the
// panel content (aio-detail and seo-detail mask `[role='tabpanel']` children,
// so the base entry measures the frame and not the panel). Everywhere else the
// base entry already compares the default tab unmasked and listing it again
// would record four identical reference PNGs for nothing.

export const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1440, height: 1100 },
];

export const LOCALES = ["en", "ar"];

// SIGV2-1138: the approved pages are not self-contained. Every one of them
// pulls the same stylesheet and the same script, and app.js is what injects
// the sidebar and nav into each page, so either file changes every reference
// render. The manifest hashed each screen's own HTML and nothing else, which
// meant an edit to signal.css would have invalidated all 80 reference PNGs
// with no hash mismatch anywhere to say so. These are hashed alongside each
// screen's source and recorded with every reference, so a change to one of
// them is a loud DESIGN_CHANGED rather than a silently stale baseline.
export const SHARED_DESIGN_ASSETS = ["signal.css", "app.js"];

// SIGV2-1138: the exclusion set for the per-tab screens of the two drilldowns.
//
// It is deliberately NOT the base screen's set. The base `fixture-elements`
// exclusion masks `main [role='tabpanel'] > *:not(:first-child)` against
// `.panelw .card, .panelw .st, .panelw .pq, ...`, i.e. the panel content
// itself, which is exactly the thing a per-tab capture exists to compare: keep
// it and the new screens would measure nothing the base screen does not
// already measure. What is kept is only what sits OUTSIDE the panel and is
// genuinely fixture-driven: the hero score gauge, the per-tab count badges,
// the target-bearing section titles, the no-target deviation and the sidebar
// switcher label. Everything inside the open panel compares raw, so these
// screens' figures are higher than the base screens' and honestly so.
const DRILLDOWN_TAB_EXCLUSIONS = [
  {
    name: "hero-fixture",
    reason:
      "Score gauge, per-tab count badges and the target-bearing section titles render the stub full_report payload. The panel content itself is NOT masked here - comparing it is the whole point of a per-tab screen.",
    designSelector: ".gwrap, .tabs .n, .sec h2",
    buildSelector: "main .h-\\[132px\\], main [role='tab'] span, main h2",
  },
  {
    name: "no-target-deviation",
    reason:
      "The design's 'Path to target' card needs a persisted score target, which does not exist in the product (SIGV2-1006). The build renders current score + a no-target state instead, deliberately.",
    designSelector: ".gap",
    buildSelector: "main .w-\\[250px\\]",
  },
  {
    name: "workspace-switcher-fixture",
    reason:
      "Sidebar switcher label is stub fixture data ('jake Workspace' vs the design's 'Northwind Group'); recorded on SIGV2-1067 as correct-as-is.",
    designSelector: ".ssw-btn",
    buildSelector: "aside button[aria-haspopup='menu']",
  },
];

export const SCREENS = [
  {
    id: "workspace-overview",
    designFile: "Signal Workspace Overview.html",
    status: "built",
    ticket: "SIGV2-1034",
    route: "/dashboard/overview",
    workspaceId: "1",
    readySelector: "a[href*='/dashboard/projects/']",
    exclusions: [
      {
        name: "project-card-copy",
        reason:
          "Card names, domains, scores, sparklines and scan ages are stub fixture data, not design copy. The card layout itself is still compared.",
        designSelector: ".pcard, .pc-body, .pc-foot",
        buildSelector: "a[href*='/dashboard/projects/']",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data ('jake Workspace' vs the design's 'Northwind Group'); recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
  },
  {
    id: "workspace-onboarding",
    designFile: "Signal Onboarding.html",
    status: "built",
    ticket: "SIGV2-1034",
    route: "/dashboard/overview",
    workspaceId: "2",
    resetStub: true,
    readySelector: "[data-testid='onboarding-wizard']",
    exclusions: [
      {
        name: "wizard-step-copy",
        reason:
          "Onboarding field values and project suggestions are stub fixture data; the modal frame and chrome are still compared.",
        designSelector: ".wiz",
        buildSelector: "[data-testid='onboarding-wizard']",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data ('Beta Workspace'); recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
  },
  {
    id: "project-overview",
    designFile: "Signal Overview.html",
    status: "built",
    ticket: "SIGV2-1035",
    route: "/dashboard/projects/9",
    workspaceId: "1",
    readySelector: "[data-metric='sessions']",
    exclusions: [
      {
        name: "chart-series",
        reason:
          "Chart paths, sparklines and plotted values come from the stub GA4/audit payload; chart geometry is not deterministic against static mockup art.",
        designSelector: "#chart, .chart, svg.chart, .spark",
        buildSelector: "canvas, .recharts-wrapper",
      },
      {
        name: "fixture-metrics",
        reason:
          "Metric values, deltas, timestamps and the provenance line are stub fixture data (SIGV2-1068 records the open product decisions around this section).",
        designSelector: ".mval, .kpi, .stat, .mono",
        buildSelector: "[data-metric], [class*='--mono']",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data; recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
  },
  {
    id: "maintenance",
    designFile: "Signal Maintenance.html",
    status: "built",
    ticket: "SIGV2-1033",
    route: "/maintenance",
    readySelector: "h1",
    exclusions: [],
  },
  {
    id: "not-found",
    designFile: "Signal 404.html",
    status: "built",
    ticket: "SIGV2-1033",
    // SignalNotFound ((app)/not-found.tsx) is only reachable through a real
    // notFound() inside (app): /admin/* calls notFound() for non-staff, and
    // the stub user is not staff. URL-guessing lands on the root marketing
    // not-found, which is not the approved screen.
    route: "/admin/overview",
    readySelector: "h1",
    exclusions: [],
  },

  {
    id: "aio-detail",
    designFile: "Signal AIO Detail.html",
    status: "built",
    ticket: "SIGV2-1036",
    designAssets: ["prompt-setup.css", "prompt-setup.js"],
    route: "/dashboard/projects/9/ai-answers",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [
      {
        name: "fixture-elements",
        reason:
          "Score gauge, Improve rows and every tab panel's content blocks render the stub full_report / visibility-summary payload. Only the fixture-bearing elements are masked (gauge, action/stat/prompt/engine rows, cards, counts, target-bearing section titles); the hero frame, eyebrow, h1, tab labels, section rows and card structure still compare.",
        designSelector:
          ".gwrap, .tabs .n, .sec h2, .lockcontent, .panelw .card, .panelw .st, .panelw .pq, .panelw .eng, .panelw .tr, .panelw .conn, .panelw .comp, .panelw .stt, .panelw .wempty",
        buildSelector:
          "main .h-\\[132px\\], main [role='tab'] span, main h2, main [role='tabpanel'] > *:not(:first-child)",
      },
      {
        name: "no-target-deviation",
        reason:
          "The design's 'Path to target' card needs a persisted score target, which does not exist in the product (SIGV2-1006). The build renders current score + a no-target state instead, deliberately.",
        designSelector: ".gap",
        buildSelector: "main .w-\\[250px\\]",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data ('jake Workspace' vs the design's 'Northwind Group'); recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
    // The default tab is listed too: the base entry above masks every panel
    // child, so Improve's content has never been compared either.
    tabs: [
      {
        id: "improve",
        captures: "Improve: the ranked AIO action rows and their locked preview state.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
      {
        id: "types",
        captures: "Search types: the five expandable search-type rows.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
      {
        id: "engines",
        captures: "By engine: the per-engine visibility cards.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
      {
        id: "prompts",
        // SIGV2-1194: the table is gone; the tab photographs the shared
        // prompt-setup surface in manage mode.
        captures:
          "Prompts: the prompt-setup surface in manage mode - coverage summary, collapsible groups per search type, editable prompt rows.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
    ],
  },
  {
    id: "seo-detail",
    designFile: "Signal SEO Detail.html",
    status: "built",
    ticket: "SIGV2-1036",
    route: "/dashboard/projects/9/google",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [
      {
        name: "fixture-elements",
        reason:
          "Score gauge, Improve rows, Ranking factors and every tab panel's content blocks render the stub full_report / serp-tracking / search-console payload. Only the fixture-bearing elements are masked (gauge, action/stat/keyword/page rows, cards, counts, target-bearing section titles); the hero frame, eyebrow, h1, tab labels, section rows and card structure still compare.",
        designSelector:
          ".gwrap, .tabs .n, .sec h2, .lockcontent, .panelw .card, .panelw .st, .panelw .pq, .panelw .eng, .panelw .tr, .panelw .conn, .panelw .comp, .panelw .stt, .panelw .wempty",
        buildSelector:
          "main .h-\\[132px\\], main [role='tab'] span, main h2, main [role='tabpanel'] > *:not(:first-child)",
      },
      {
        name: "no-target-deviation",
        reason:
          "The design's 'Path to target' card needs a persisted score target, which does not exist in the product (SIGV2-1006). The build renders current score + a no-target state instead, deliberately.",
        designSelector: ".gap",
        buildSelector: "main .w-\\[250px\\]",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data; recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
    // The default tab is listed too: the base entry above masks every panel
    // child, so Improve's content has never been compared either.
    tabs: [
      {
        id: "improve",
        captures: "Improve: the ranked SEO action rows and their locked preview state.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
      {
        id: "factors",
        captures: "Ranking factors: the factor scorecards.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
      {
        id: "keywords",
        captures: "Keywords: the tracked-keyword table and its empty/locked states.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
      {
        id: "pages",
        captures: "Pages: the per-page performance table.",
        exclusions: DRILLDOWN_TAB_EXCLUSIONS,
      },
    ],
  },

  // ------------------------------------------------------------------
  // SIGV2-1115: the ten screens below were flagged "not-implemented" and
  // skipped in silence. Every one of them is in fact built - each route
  // below resolves to a real page under frontend/src/app and renders. They
  // are now compared like any other screen.
  //
  // They carry no `exclusions` on purpose. Their divergence figures are
  // therefore raw and unmasked: nothing about them is hidden to make a
  // number look better, and the thresholds recorded in thresholds.json are
  // the raw measurements. Tightening these screens (and only then adding
  // justified fixture exclusions, each named and reasoned like the ones
  // above) is the follow-up work the ratchet exists to drive.
  // ------------------------------------------------------------------
  {
    id: "developer-hub",
    designFile: "Signal Developer Hub.html",
    status: "built",
    ticket: "SIGV2-1042",
    route: "/dashboard/developer",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [],
    // Hub is the default tab and is already compared, unmasked, by the entry
    // above.
    tabs: [
      { id: "quickstart", captures: "Quick Start: the onboarding steps and code samples." },
      { id: "reference", captures: "API Reference: the endpoint reference surface." },
    ],
  },
  {
    id: "audit-start",
    designFile: "Signal Audit.html",
    status: "built",
    ticket: "SIGV2-1038",
    designAssets: ["prompt-setup.css", "prompt-setup.js"],
    // SIGV2-1194: the prompts section only loads when a project is named, and
    // the approved design draws the full prompt-setup surface, so the route
    // carries the Northwind project explicitly.
    route: "/dashboard/audit?projectId=9",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [],
  },
  {
    id: "audit-run",
    designFile: "Signal Audit Run.html",
    status: "built",
    ticket: "SIGV2-1038",
    // Audit 901 is not in the stub fixture set, so the built page renders its
    // real "audit not found" state. That is a genuine render of the route and
    // is compared as such; the divergence it reports against the approved run
    // screen is real and is what SIGV2-1038 has to close.
    route: "/dashboard/audit/901",
    workspaceId: "1",
    readySelector: "h1, h2",
    exclusions: [],
  },
  {
    id: "billing",
    designFile: "Signal Billing.html",
    status: "built",
    ticket: "SIGV2-1040",
    route: "/dashboard/billing",
    workspaceId: "1",
    readySelector: "[role='tablist']",
    exclusions: [],
    // Overview is the default tab and is already compared, unmasked, by the
    // entry above.
    tabs: [
      { id: "usage", captures: "Usage: the scan-usage meters and history." },
      { id: "plans", captures: "Plans: the plan cards and the interval switch." },
      // SIGV2-1165: the Commitments tab is withdrawn from the built page, so
      // the design's commitments panel has no built counterpart to compare.
      { id: "comparison", captures: "Comparison: the plan feature comparison table." },
    ],
  },
  {
    id: "billing-success",
    designFile: "Signal Billing Success.html",
    status: "built",
    ticket: "SIGV2-1040",
    route: "/dashboard/billing/success",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [],
  },
  {
    id: "billing-cancel",
    designFile: "Signal Billing Cancel.html",
    status: "built",
    ticket: "SIGV2-1040",
    route: "/dashboard/billing/cancel",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [],
  },
  {
    id: "billing-history",
    designFile: "Signal Billing History.html",
    status: "built",
    ticket: "SIGV2-1040",
    route: "/dashboard/billing/history",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [],
  },
  {
    id: "competitors",
    designFile: "Signal Competitors.html",
    status: "built",
    ticket: "SIGV2-1037",
    route: "/dashboard/projects/9/competitors",
    workspaceId: "1",
    readySelector: "h1",
    // The approved file ships `body.locked` (the Specialist gate over blurred
    // content); its own "Preview competitors (demo)" button removes the class.
    // The comparison renders that unlocked state, which is the state entitled
    // plans actually see and the only state whose content can be measured.
    designUnlockBodyClass: "locked",
    exclusions: [
      {
        name: "fixture-values",
        reason:
          "Rank badge number, hero rank sentence and intro, gap-to-#1 figures, leaderboard cell values (names, scores, 30-day/gap), chart series and legend names all render the stub competitive payload; the design holds static fixture copy. Only value-bearing elements are masked - hero frame, card frames, table head, section headers and row labels still compare.",
        designSelector:
          ".rank-badge, .hero h1, .hero p, .gap, tbody td, .legend, .chart, .vs .bars",
        buildSelector:
          "main [data-testid='comp-rank-badge'], main h1, main h1 + p, main [data-testid='comp-gap-card'], main td, main [data-testid='comp-trend-chart'], main [data-testid='comp-chart-legend']",
      },
      {
        name: "chart-window-deviation",
        reason:
          "The design captions the chart 'blended AIO + SEO · last 6 months', but the trends endpoint offers 30d|90d|1y|all only; the build requests 1y and captions the window the endpoint actually returned (deliberate, SIGV2-1037).",
        designSelector: ".chead .mini, .sec .mini",
        buildSelector: "main [data-chart-caption]",
      },
      {
        name: "unmeasured-rows",
        reason:
          "The design fabricates per-engine mention bars (Grok 9/10 etc.); the product has no source for them, so the build renders 'Not measured' placeholders in the same rows (deliberate, B5). The design's 'BEHIND' chip on those two card headers is also absent from the build: it asserted a standing over six unmeasured rows, so it was removed (deliberate, SIGV2-1116).",
        designSelector: ".vs .bars",
        buildSelector: "main [data-unmeasured]",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data ('jake Workspace' vs the design's 'Northwind Group'); recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
  },
  {
    id: "fixes",
    designFile: "Signal Fixes.html",
    status: "built",
    ticket: "SIGV2-1037",
    route: "/dashboard/projects/9/fixes",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [
      {
        name: "fixture-plan-rows",
        reason:
          "Each plan row's rank, title, description, chips and actions come from the stub advisor payload and task board; the design holds six static rows. The row elements are fixture data themselves, so each row is masked, never its container. Pagehead, alert, filter bar and footer copy still compare.",
        designSelector: ".fix",
        buildSelector: "[data-testid^='fix-'], [data-testid^='fix-done-']",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data ('jake Workspace' vs the design's 'Northwind Group'); recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
  },
  {
    id: "settings",
    designFile: "Signal Settings.html",
    status: "built",
    ticket: "SIGV2-1039",
    route: "/dashboard/projects/9/settings",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [
      {
        name: "fixture-field-values",
        reason:
          "Field values, toggle states, chips, connection states, targets and table cells come from the stub project/settings payload; the design holds static values. Only the value-bearing controls and cells are masked - every card frame, header, label, description and button still compares.",
        designSelector:
          ".winput, .wselect, .wtextarea, .wsv, .fl b, .range-track, .comp:not(.add), .conn .badge-ok, .conn button, .switchT, .wtable td, .wempty, .wn, .swatch, .wstep, .wsc, .wstat, .wupload, .field .seg, .panelw .seg",
        buildSelector:
          "main input, main select, main textarea, main [role='switch'], main [role='checkbox'], main [role='radio'], main [role='slider'], main td, main output",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data ('jake Workspace' vs the design's 'Northwind Group'); recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
    // Product is the default tab. The exclusions above are selector-based and
    // resolve inside whichever tab is open, so the per-tab screen inherits
    // them unchanged: they mask field values, never a whole panel.
    tabs: [{ id: "brand", captures: "Brand & competitors: brand voice and competitive intake." }],
  },
  {
    id: "workspace-settings",
    designFile: "Signal Workspace Settings.html",
    status: "built",
    ticket: "SIGV2-1039",
    route: "/dashboard/settings",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [
      {
        name: "fixture-field-values",
        reason:
          "Field values, toggle states, swatches, upload state, steps and table cells come from the stub workspace/settings payload; the design holds static values. Only the value-bearing controls and cells are masked - every card frame, header, label, description and button still compares.",
        designSelector:
          ".winput, .wselect, .wtextarea, .wsv, .fl b, .range-track, .comp:not(.add), .conn .badge-ok, .conn button, .switchT, .wtable td, .wempty, .wn, .swatch, .wstep, .wsc, .wstat, .wupload, .field .seg, .panelw .seg",
        buildSelector:
          "main input, main select, main textarea, main [role='switch'], main [role='checkbox'], main [role='radio'], main [role='slider'], main td, main output",
      },
      {
        name: "workspace-switcher-fixture",
        reason:
          "Sidebar switcher label is stub fixture data ('jake Workspace' vs the design's 'Northwind Group'); recorded on SIGV2-1067 as correct-as-is.",
        designSelector: ".ssw-btn",
        buildSelector: "aside button[aria-haspopup='menu']",
      },
    ],
    // General is the default tab (the build calls it "workspace-overview",
    // hence the explicit buildTab on every row). Exclusions are inherited:
    // they mask field values, never a whole panel.
    tabs: [
      {
        id: "team",
        buildTab: "workspace-team",
        captures: "Team: the internal member table and the invite form.",
      },
      {
        id: "client",
        buildTab: "workspace-client-access",
        captures: "Client Access: the client portal invitations and project assignment.",
      },
      {
        id: "whitelabel",
        buildTab: "workspace-white-label",
        captures: "White-Label: brand assets, accent colours, sender and custom domain.",
      },
      {
        id: "developer",
        buildTab: "workspace-developer",
        captures: "Developer: API keys and the usage cost breakdown.",
      },
    ],
  },
  {
    id: "my-profile",
    designFile: "Signal My Profile.html",
    status: "built",
    ticket: "SIGV2-1039",
    route: "/dashboard/account-settings",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [],
    // Profile is the default tab and is already compared, unmasked, by the
    // entry above. The Data tab is the one whose rebuild could not be
    // confirmed before SIGV2-1138, because the figure was taken on the
    // Profile tab on both sides.
    tabs: [
      { id: "security", captures: "Security: password, MFA and session controls." },
      { id: "notifications", captures: "Notifications: the per-channel notification toggles." },
      { id: "branding", captures: "Branding: the personal branding card." },
      { id: "data", captures: "Data: the export, retention and account-deletion rights." },
    ],
  },
  {
    id: "reports",
    designFile: "Signal Reports.html",
    status: "built",
    ticket: "SIGV2-1130",
    // SIGV2-1130 corrects the route. The approved page is the Report library,
    // and this entry pointed at /dashboard/projects/9/reports, which is the
    // project-scoped monthly progress reporting screen: a different product
    // surface with a different data contract, so the figure it produced was
    // measuring two unrelated pages against each other. The library is the
    // workspace Reports screen and now exists at /dashboard/reports.
    route: "/dashboard/reports",
    workspaceId: "1",
    readySelector: "h1",
    exclusions: [],
  },
];

// Approved pages deliberately absent from the catalogue above, with the
// reason they are not compared. This is the ONLY sanctioned way for an
// approved page not to be compared: every entry is printed into every run's
// report.md, so an exclusion is a standing, visible statement rather than a
// silent skip.
export const EXCLUDED_DESIGNS = [
  {
    designFile: "Signal Agents.html",
    reason: "Deliberately 'coming soon' in the product plan; no build target.",
  },
  {
    designFile: "Signal Gate.html",
    reason:
      "SIGV2-1115: the catalogue mapped this to the /gate route, which is wrong and produced " +
      "a meaningless 96% figure. The approved page is the plan paywall ('Competitor reports " +
      "are a Specialist feature', plan cards, contact-sales routes) inside the app shell. " +
      "The /gate route is the unrelated private-preview password gate (SIGNAL_GATE_PASSWORD, " +
      "src/lib/signalGate.ts). The paywall IS built, but only as an in-page state " +
      "(components/dashboard/PlanLockNotice.tsx driven by lib/planLocks.ts, plus the locked " +
      "state the competitors screen already covers through designUnlockBodyClass); it has no " +
      "standalone route to render, so there is nothing to photograph as a screen. Giving the " +
      "paywall its own route under SIGV2-1040 would make it comparable; until then, comparing " +
      "it to /gate measures nothing.",
  },
  {
    designFile: "Signal Data Feed.html",
    reason: "Deliberately 'coming soon' in the product plan; no build target.",
  },
  {
    designFile: "Signal Components.html",
    reason: "Internal design-system reference sheet, not a customer screen.",
  },
];

// SIGV2-1138: the comparison id of a per-tab screen. Kept in one place
// because it names reference PNGs, manifest keys and threshold keys.
export const tabScreenId = (screenId, tabId) => `${screenId}-tab-${tabId}`;

// SIGV2-1138: expand the authored catalogue into render groups.
//
// One group per approved page. Inside a group each "state" is one comparison
// screen: the base state (whatever tab each side opens on) followed by one
// state per declared tab. States of a group share a single page load per
// viewport and locale - the tab is clicked and the page re-photographed, which
// is why adding tabs costs settle time rather than another cold navigation.
// The base state is always first, so it is captured before any click.
export function screenGroups() {
  return SCREENS.map((screen) => ({
    screen,
    states: [
      {
        id: screen.id,
        screen,
        tab: null,
        exclusions: screen.exclusions ?? [],
      },
      ...(screen.tabs ?? []).map((tab) => ({
        id: tabScreenId(screen.id, tab.id),
        screen,
        tab: {
          id: tab.id,
          design: tab.designTab ?? tab.id,
          build: tab.buildTab ?? tab.id,
          captures: tab.captures ?? null,
        },
        exclusions: tab.exclusions ?? screen.exclusions ?? [],
      })),
    ],
  }));
}

// Every comparison screen id, base states and tab states interleaved in
// catalogue order. Used to order thresholds.json deterministically.
export const COMPARISON_SCREEN_IDS = screenGroups().flatMap((g) => g.states.map((s) => s.id));
