import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const frontendRoot = path.resolve(__dirname, "../..");
const readFrontendSource = (relativePath: string) =>
  fs.readFileSync(path.join(frontendRoot, relativePath), "utf8");

const overviewPageSource = readFrontendSource(
  "src/app/(app)/dashboard/projects/[projectId]/page.tsx"
);
// SIGV2-1035 extracted the score rings and panel grid out of the route file;
// the mobile markers for them live on this component now.
const visibilityPanelsSource = readFrontendSource("src/components/dashboard/VisibilityPanels.tsx");
const aioPageSource = readFrontendSource(
  "src/app/(app)/dashboard/projects/[projectId]/ai-answers/page.tsx"
);
const signalTabsSource = readFrontendSource("src/components/signal/SignalTabs.tsx");
const seoPageSource = readFrontendSource(
  "src/app/(app)/dashboard/projects/[projectId]/google/page.tsx"
);
const automationsPageSource = readFrontendSource(
  "src/app/(app)/dashboard/projects/[projectId]/automations/ProjectAutomationsClient.tsx"
);
const profileSectionSource = readFrontendSource(
  "src/app/(app)/dashboard/account-settings/components/ProfileSection.tsx"
);
const developerPageSource = readFrontendSource("src/app/(app)/dashboard/developer/page.tsx");
const settingsPageSource = readFrontendSource("src/app/(app)/dashboard/settings/page.tsx");
const billingSource = readFrontendSource("src/app/(app)/dashboard/billing/page.tsx");
const connectionsSource = readFrontendSource("src/app/(app)/dashboard/connections/page.tsx");
const connectionsPanelsSource = readFrontendSource(
  "src/components/dashboard/settings/ConnectionsPanels.tsx"
);

const expectMarkersInOrder = (source: string, markers: string[]) => {
  let previousIndex = -1;
  for (const marker of markers) {
    const markerIndex = source.indexOf(marker);
    expect(markerIndex, `Missing required source marker: ${marker}`).toBeGreaterThanOrEqual(0);
    expect(markerIndex, `Source marker is out of order: ${marker}`).toBeGreaterThan(previousIndex);
    previousIndex = markerIndex;
  }
};

describe("Signal mobile reflow preliminary source contracts", () => {
  it("rejects a missing source-order marker instead of treating indexOf -1 as ordered", () => {
    expect(() => expectMarkersInOrder("first third", ["first", "second", "third"])).toThrow(
      "Missing required source marker: second"
    );
  });

  it("keeps the portaled mobile navigation inside the same light theme", () => {
    const drawer = readFrontendSource("src/components/app/MobileDashboardDrawer.tsx");
    expect(drawer).toContain("data-signal-theme");
    expect(drawer).toContain("max-w-full");
    expect(drawer).toContain("focus-visible:ring-2");
  });

  it("MOBILE-R1 preliminarily stacks the Project Overview score grid", () => {
    // Preliminary source contract: JSDOM does not calculate responsive grid geometry.
    // The approved two-panel grid is one column until xl.
    expect(visibilityPanelsSource).toContain("grid grid-cols-1 gap-4 xl:grid-cols-2");
  });

  it("reserves the complete Overview gauge box when the score is unavailable", () => {
    expect(visibilityPanelsSource).toContain("relative w-[150px] flex-none text-center");
    expect(visibilityPanelsSource).toContain("relative z-[2] -mt-[90px]");
  });

  it("keeps the Overview locked card in the layout even with an empty action list", () => {
    expect(overviewPageSource).toContain('!canAction && "grid"');
    expect(overviewPageSource).toContain("col-start-1 row-start-1");
  });

  it("reserves the full AI answer gauge box above the mobile heading", () => {
    expect(aioPageSource).toContain("relative h-[132px] w-[132px]");
    expect(aioPageSource).toContain(
      "absolute inset-0 mt-0 flex flex-col items-center justify-center"
    );
  });

  it("keeps the AI answer lock card in the flow for a short action list", () => {
    expect(aioPageSource).toContain('!advisorPlan.allowed && "grid"');
    expect(aioPageSource).toContain("col-start-1 row-start-1");
  });

  it("MOBILE-R2 preliminarily stacks the AIO hero", () => {
    expect(aioPageSource).toContain("max-md:flex-col max-md:items-stretch");
  });

  it("MOBILE-R2 requires every SEO gauge-copy-target marker in source order", () => {
    // Asserted against the route that actually renders, google/page.tsx. The hero
    // reflow is expressed as max-md: utilities since the bespoke class sweep.
    expectMarkersInOrder(seoPageSource, [
      'className="relative flex items-center gap-[26px]',
      'className="relative h-[132px] w-[132px]',
      'className="min-w-0 flex-1"',
      'className="text-[11px] uppercase tracking-[0.14em] text-(--blue)"',
      'className="w-[250px] flex-none rounded-[12px]',
    ]);
    expect(seoPageSource).toContain("max-md:flex-col max-md:items-stretch");
  });

  it("MOBILE-R4 preliminarily makes the Automations grid one column", () => {
    expect(automationsPageSource).toContain("grid grid-cols-1 gap-3.5 md:grid-cols-2");
  });

  it("MOBILE-R5 preliminarily makes Profile two- and three-field grids one column", () => {
    expect(profileSectionSource).toContain("grid grid-cols-1 gap-4 md:grid-cols-2");
    expect(profileSectionSource).toContain("grid grid-cols-1 gap-4 md:grid-cols-3");
  });

  it("MOBILE-R6 keeps Billing tabs local and uses compact mobile subscription-card padding", () => {
    expect(billingSource).toContain("<SignalTabs");
    expect(signalTabsSource).toContain("overflow-x-auto");
    // Preliminary source contract: JSDOM cannot measure the card against a 320px viewport.
    expect(/<GlassCard[^>]*className="[^"]*p-(?:4|5)[^"]*sm:p-6/.test(billingSource)).toBe(true);
  });

  it("MOBILE-R7 preliminarily stacks Developer metrics", () => {
    // The fstat row stacks below md exactly as the deleted .sg media rule did.
    expect(developerPageSource).toContain("flex gap-3.5 max-md:flex-col");
  });

  it("stacks the settings inline field rows and wraps workspace toggle rows", () => {
    expect(settingsPageSource).toContain("max-md:flex-col max-md:items-stretch");
    expect(settingsPageSource).toContain("max-md:flex-wrap max-md:items-start");
  });

  it("Connections renders as settings-section cards with no local tab chrome", () => {
    expect(connectionsSource).toContain("<ConnectionsPanels />");
    // SIGV2-1039: the panels are no longer also inlined into Workspace
    // Settings. The approved Workspace Settings page has no Connections block
    // at all (its General tab is Workspace Identity plus My Workspaces), and
    // rendering them in both places made that page roughly 40% taller than the
    // design. /dashboard/connections above is the single home, and it is where
    // the overview CTA, ConnectedDataSection, SiteTrafficSection, the task
    // board and the Jira modal already link.
    expect(settingsPageSource).not.toContain("<ConnectionsPanels />");
    expect(connectionsPanelsSource).not.toContain("<SignalTabs");
    // MVP `.conn` anatomy: flat hairline-separated rows, no nested tile grid.
    expect(connectionsPanelsSource).toContain("border-t border-t-(--line-2) py-3 first:border-t-0");
    expect(connectionsPanelsSource).not.toContain("lg:grid-cols-2");
    expect(signalTabsSource).toContain("max-w-full");
    expect(signalTabsSource).toContain("overflow-x-auto");
  });
});
