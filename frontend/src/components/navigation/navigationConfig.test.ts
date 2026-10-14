import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  adminQuickLinks,
  flattenNavSections,
  getProjectNavSections,
  isRouteActive,
  type NavItem,
  normalizeProjectScopeId,
  projectWorkspaceQuickLinks,
  resolveProjectBasePath,
  workspaceNavSections,
} from "@/components/navigation/navigationConfig";

const byName = (items: NavItem[], name: string) => items.find((item) => item.name === name);

const srcDir = path.resolve(__dirname, "../..");
const appDir = path.join(srcDir, "app");

/**
 * Resolve a nav href to the App Router file that serves it, mirroring the two
 * routing rules that matter here: `(group)` directories do not consume a URL
 * segment, and `[param]` directories match any single segment. Returns null
 * when nothing serves the href (for example `#`).
 */
function findRouteFile(segments: string[], dir: string): string | null {
  if (segments.length === 0) {
    for (const file of ["page.tsx", "page.ts", "route.ts"]) {
      const candidate = path.join(dir, file);
      if (fs.existsSync(candidate)) return candidate;
    }
    return null;
  }

  const [head, ...rest] = segments;
  const dirs = fs.existsSync(dir)
    ? fs
        .readdirSync(dir, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
    : [];

  for (const name of dirs.filter((name) => name === head)) {
    const hit = findRouteFile(rest, path.join(dir, name));
    if (hit) return hit;
  }
  for (const name of dirs.filter((name) => /^\[.+\]$/.test(name))) {
    const hit = findRouteFile(rest, path.join(dir, name));
    if (hit) return hit;
  }
  for (const name of dirs.filter((name) => /^\(.+\)$/.test(name))) {
    const hit = findRouteFile(segments, path.join(dir, name));
    if (hit) return hit;
  }
  return null;
}

const routeFileFor = (href: string): string | null =>
  href.startsWith("/") ? findRouteFile(href.split("/").filter(Boolean), appDir) : null;

/**
 * A route counts as "wired" when the page, or something it renders within two
 * import hops, talks to the backend: a service module, a data hook, or a raw
 * fetch. Two hops covers the shape this app uses everywhere (page -> client ->
 * panels) without walking the whole module graph.
 */
const DATA_SOURCE = /from\s+"@\/services\/|from\s+"@\/hooks\/|fetch\(|apiFetch|useSWR/;

function resolveImport(spec: string, fromFile: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = path.join(srcDir, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(fromFile), spec);
  else return null;

  for (const suffix of [".tsx", ".ts", "/index.tsx", "/index.ts"]) {
    if (fs.existsSync(base + suffix)) return base + suffix;
  }
  return null;
}

function isRouteWired(routeFile: string): boolean {
  const seen = new Set<string>();
  let frontier = [routeFile];

  for (let hop = 0; hop <= 2 && frontier.length > 0; hop += 1) {
    const next: string[] = [];
    for (const file of frontier) {
      if (seen.has(file)) continue;
      seen.add(file);
      const source = fs.readFileSync(file, "utf8");
      if (DATA_SOURCE.test(source)) return true;
      for (const match of source.matchAll(/from\s+"([^"]+)"/g)) {
        const target = resolveImport(match[1], file);
        if (target && !seen.has(target)) next.push(target);
      }
    }
    frontier = next;
  }
  return false;
}

const allNavItems = (): NavItem[] => [
  ...flattenNavSections(getProjectNavSections("/dashboard/projects/123")),
  ...flattenNavSections(workspaceNavSections),
  ...projectWorkspaceQuickLinks.items,
  ...adminQuickLinks.items,
];

describe("navigationConfig", () => {
  it("renders the approved project IA in order, under the approved group labels", () => {
    const sections = getProjectNavSections("/dashboard/projects/123");

    expect(sections.map((section) => section.label)).toEqual([
      "Intelligence",
      "Automation",
      "Account",
    ]);
    expect(sections.map((section) => section.items.map((item) => item.name))).toEqual([
      ["Dashboard", "AIO score", "SEO score", "Competitors", "Entities"],
      ["Tasks"],
      ["Settings", "Sign out"],
    ]);
  });

  it("points each approved destination at its real existing route", () => {
    const items = flattenNavSections(getProjectNavSections("/dashboard/projects/123"));
    const base = "/dashboard/projects/123";

    expect(byName(items, "Dashboard")?.href).toBe(base);
    expect(byName(items, "AIO score")?.href).toBe(`${base}/ai-answers`);
    expect(byName(items, "SEO score")?.href).toBe(`${base}/google`);
    expect(byName(items, "Competitors")?.href).toBe(`${base}/competitors`);
    // SOON entries carry no href: the approved markup is `href="#"`, and the
    // honest equivalent is no link at all, never a route to a page that is
    // not ready.
    expect(byName(items, "Entities")?.href).toBeUndefined();
    expect(byName(items, "Tasks")?.href).toBeUndefined();
    expect(byName(items, "Settings")?.href).toBe(`${base}/settings`);
  });

  it("marks only Entities and Tasks as non-navigating SOON entries", () => {
    const items = flattenNavSections(getProjectNavSections("/dashboard/projects/123"));

    const soon = items.filter((item) => item.disabled);
    expect(soon.map((item) => item.name)).toEqual(["Entities", "Tasks"]);
    for (const item of soon) {
      expect(item.badge, item.name).toBe("SOON");
      expect(item.badgeKey, item.name).toBe("nav.soon");
    }
    for (const item of items.filter((item) => !item.disabled && !item.action)) {
      expect(item.href, item.name).toMatch(/^\//);
    }
  });

  it("keeps Fixes and the internal Components catalogue out of the sidebar", () => {
    const names = flattenNavSections(getProjectNavSections("/dashboard/projects/123")).map(
      (item) => item.name
    );

    // Approved design: Fixes is reached from the dashboard actions and the
    // AIO drilldown, never from the sidebar. Components is an internal
    // catalogue page in the mockup, not customer IA.
    for (const gone of ["Fixes", "What to fix next", "Components", "Reference"]) {
      expect(names, gone).not.toContain(gone);
    }
  });

  it("carries Sign out as an action item, never a link", () => {
    for (const items of [
      flattenNavSections(getProjectNavSections("/dashboard/projects/123")),
      flattenNavSections(workspaceNavSections),
    ]) {
      const signOut = byName(items, "Sign out");
      expect(signOut, "Sign out").toBeDefined();
      expect(signOut!.action).toBe("logout");
      expect(signOut!.href).toBeUndefined();
    }
  });

  it("uses no route twice", () => {
    const hrefs = flattenNavSections(getProjectNavSections("/dashboard/projects/123"))
      .map((item) => item.href)
      .filter((href): href is string => Boolean(href));

    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("never links a clickable nav item at a route that is missing or unwired", () => {
    const broken = allNavItems()
      .filter((item) => !item.disabled && !item.action && item.href)
      .map((item) => ({ item, routeFile: routeFileFor(item.href!) }))
      .filter(({ routeFile }) => routeFile === null || !isRouteWired(routeFile))
      .map(({ item, routeFile }) =>
        routeFile === null
          ? `${item.name} (${item.href}) has no App Router page`
          : `${item.name} (${item.href}) resolves to ${routeFile} but reaches no data source`
      );

    expect(broken, "These nav items are presented as working but lead nowhere real.").toEqual([]);
  });

  it("keeps every label translatable through an i18n key", () => {
    for (const section of [
      ...getProjectNavSections("/dashboard/projects/123"),
      ...workspaceNavSections,
    ]) {
      expect(section.labelKey, section.label).toMatch(/^nav\./);
      for (const item of section.items) {
        expect(item.nameKey, item.name).toMatch(/^nav\./);
      }
    }
  });

  it("renders the approved workspace IA in order, under the approved group labels", () => {
    expect(workspaceNavSections.map((section) => section.label)).toEqual(["Workspace", "Account"]);
    expect(workspaceNavSections.map((section) => section.items.map((item) => item.name))).toEqual([
      ["Overview", "Workspace Settings", "My Profile", "Billing", "Developer Hub"],
      ["Sign out"],
    ]);
  });

  it("points the workspace items at their existing routes", () => {
    const items = flattenNavSections(workspaceNavSections);

    expect(byName(items, "Overview")?.href).toBe("/dashboard");
    expect(byName(items, "Workspace Settings")?.href).toBe("/dashboard/settings");
    expect(byName(items, "My Profile")?.href).toBe("/dashboard/account-settings");
    expect(byName(items, "Billing")?.href).toBe("/dashboard/billing");
    expect(byName(items, "Developer Hub")?.href).toBe("/dashboard/developer");
  });

  it("treats /dashboard and /dashboard/overview as active for workspace home", () => {
    expect(isRouteActive("/dashboard", "/dashboard")).toBe(true);
    expect(isRouteActive("/dashboard/overview", "/dashboard")).toBe(true);
    expect(isRouteActive("/dashboard/projects/10", "/dashboard")).toBe(false);
  });

  // SIGV2-1180: a scan, its history and its report sit outside the project
  // segment, so the menu scope cannot come from the pathname alone.
  it("keeps the project scope on a scan that names its project", () => {
    expect(resolveProjectBasePath("/dashboard/audit", "10")).toBe("/dashboard/projects/10");
    expect(resolveProjectBasePath("/dashboard/audit", 10)).toBe("/dashboard/projects/10");
    expect(resolveProjectBasePath("/dashboard/audit/", "10")).toBe("/dashboard/projects/10");
    expect(resolveProjectBasePath("/dashboard/audit/501", 10)).toBe("/dashboard/projects/10");
  });

  it("keeps the pathname's project whatever a query string names", () => {
    expect(resolveProjectBasePath("/dashboard/projects/10/google", "77")).toBe(
      "/dashboard/projects/10"
    );
  });

  it("stays workspace-scoped when no project is named, and off project-less routes", () => {
    // The approved workspace-level scan form, reached from the workspace
    // overview: no project, so the workspace menu is the right one.
    expect(resolveProjectBasePath("/dashboard/audit", null)).toBeNull();
    expect(resolveProjectBasePath("/dashboard/audit")).toBeNull();
    expect(resolveProjectBasePath("/dashboard/audit/501")).toBeNull();
    // A project id on a workspace route grants it no project scope.
    expect(resolveProjectBasePath("/dashboard/settings", "10")).toBeNull();
    expect(resolveProjectBasePath("/dashboard/billing", "10")).toBeNull();
    expect(resolveProjectBasePath("/dashboard", "10")).toBeNull();
    // Not the scan route, merely a prefix of it.
    expect(resolveProjectBasePath("/dashboard/audits", "10")).toBeNull();
  });

  it("accepts only a positive integer as a project id", () => {
    for (const accepted of ["7", 7, " 7 ", "007"]) {
      expect(normalizeProjectScopeId(accepted), String(accepted)).toBe("7");
    }
    // The id is interpolated into the sidebar's hrefs, so anything else
    // resolves to no scope rather than being escaped into one.
    for (const rejected of [
      "",
      " ",
      "0",
      "-1",
      "1.5",
      "1e3",
      "abc",
      "7/../../admin",
      "../../admin/users",
      "7%2Fadmin",
      "javascript:alert(1)",
      null,
      undefined,
    ]) {
      expect(normalizeProjectScopeId(rejected), String(rejected)).toBeNull();
      expect(resolveProjectBasePath("/dashboard/audit", rejected), String(rejected)).toBeNull();
    }
  });

  it("treats project overview as exact-only so child modules do not keep it active", () => {
    expect(isRouteActive("/dashboard/projects/10", "/dashboard/projects/10")).toBe(true);
    expect(isRouteActive("/dashboard/projects/10/overview", "/dashboard/projects/10")).toBe(true);
    expect(isRouteActive("/dashboard/projects/10/seo", "/dashboard/projects/10")).toBe(false);
    expect(isRouteActive("/dashboard/projects/10/aeo", "/dashboard/projects/10")).toBe(false);
  });
});
