import type { CSSProperties } from "react";

import { BRAND_HEX } from "@/lib/brandPalette";
import type { WorkspaceWhiteLabelSettings } from "@/services/workspaceService";

export type WorkspaceBrandingPayload = Pick<
  WorkspaceWhiteLabelSettings,
  | "workspace_name"
  | "company_name"
  | "custom_page_title"
  | "custom_logo_url"
  | "custom_favicon_url"
  | "primary_color"
  | "secondary_color"
  | "hide_powered_by"
>;

const HEX_COLOR_PATTERN = /^#(?:[0-9A-F]{6})$/i;

const DASHBOARD_SEGMENT_LABELS: Record<string, string> = {
  "": "Workspace Overview",
  overview: "Workspace Overview",
  audit: "Audit Workspace",
  billing: "Billing",
  connections: "Connections",
  settings: "Workspace Settings",
  "account-settings": "My Profile",
  reports: "Reports",
  developer: "Developer",
  leads: "Leads",
};

const PROJECT_SEGMENT_LABELS: Record<string, string> = {
  "": "Project Dashboard",
  aeo: "AI answers",
  automations: "Automations",
  competitive: "Competitive",
  entities: "Entities",
  "entity-authority": "Entity Authority",
  geo: "AI visibility",
  monitoring: "Monitoring",
  recommendations: "Recommendations",
  reports: "Reports",
  seo: "SEO",
  settings: "Settings",
  "site-crawl": "Site Crawl",
  tasks: "Tasks",
  timeline: "Timeline",
};

const clampAlpha = (alpha: number) => Math.max(0, Math.min(1, alpha));

const normalizeHexColor = (value: string | null | undefined, fallback: string) =>
  value && HEX_COLOR_PATTERN.test(value) ? value.toUpperCase() : fallback.toUpperCase();

const humanizeSegment = (value: string) =>
  value
    .trim()
    .split("-")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");

const mixHexColors = (base: string, target: string, ratio: number) => {
  if (!HEX_COLOR_PATTERN.test(base) || !HEX_COLOR_PATTERN.test(target)) {
    return base;
  }

  const normalizedRatio = clampAlpha(ratio);
  const [baseRed, baseGreen, baseBlue] = [
    Number.parseInt(base.slice(1, 3), 16),
    Number.parseInt(base.slice(3, 5), 16),
    Number.parseInt(base.slice(5, 7), 16),
  ];
  const [targetRed, targetGreen, targetBlue] = [
    Number.parseInt(target.slice(1, 3), 16),
    Number.parseInt(target.slice(3, 5), 16),
    Number.parseInt(target.slice(5, 7), 16),
  ];

  const toHex = (value: number) => Math.round(value).toString(16).padStart(2, "0").toUpperCase();

  return `#${toHex(baseRed + (targetRed - baseRed) * normalizedRatio)}${toHex(
    baseGreen + (targetGreen - baseGreen) * normalizedRatio
  )}${toHex(baseBlue + (targetBlue - baseBlue) * normalizedRatio)}`;
};

const withHexAlpha = (value: string, alphaHex: string) =>
  HEX_COLOR_PATTERN.test(value) ? `${value}${alphaHex.toUpperCase()}` : value;

export function resolveWorkspaceBrandName(
  branding: WorkspaceBrandingPayload | null | undefined
): string {
  const companyName = branding?.company_name?.trim();
  if (companyName) {
    return companyName;
  }

  const workspaceName = branding?.workspace_name?.trim();
  if (workspaceName) {
    return workspaceName;
  }

  return "Workspace";
}

export function resolveWorkspaceBrandingStyle(
  branding: WorkspaceBrandingPayload | null | undefined
): CSSProperties {
  const primaryColor = normalizeHexColor(branding?.primary_color, BRAND_HEX.atlasBlue);
  const secondaryColor = normalizeHexColor(branding?.secondary_color, BRAND_HEX.signalTeal);

  return {
    "--primary": primaryColor,
    "--primary-hover": mixHexColors(primaryColor, "#000000", 0.18),
    "--accent": secondaryColor,
    "--color-primary": primaryColor,
    "--color-accent": secondaryColor,
    "--ring": mixHexColors(primaryColor, "#FFFFFF", 0.42),
    "--sky-300": mixHexColors(primaryColor, "#FFFFFF", 0.32),
    "--chart-1": primaryColor,
    "--chart-2": secondaryColor,
    "--shadow-primary": `0 10px 24px ${withHexAlpha(primaryColor, "24")}`,
    "--selection": withHexAlpha(primaryColor, "3D"),
  } as CSSProperties;
}

export function resolveDashboardDocumentTitle(
  pathname: string,
  branding: WorkspaceBrandingPayload | null | undefined,
  projectName?: string | null
): string {
  const trimmedTitle = branding?.custom_page_title?.trim();
  const baseTitle = trimmedTitle || resolveWorkspaceBrandName(branding);
  const path = pathname.split("?")[0] || "/dashboard";
  const segments = path.split("/").filter(Boolean);

  if (segments[0] !== "dashboard") {
    return baseTitle;
  }

  if (segments[1] === "projects") {
    const sectionKey = segments[3] ?? "";
    const humanizedSection = humanizeSegment(sectionKey);
    const sectionLabel =
      PROJECT_SEGMENT_LABELS[sectionKey] ?? (humanizedSection || "Project Dashboard");
    const titleParts = [projectName?.trim(), sectionLabel].filter((value): value is string =>
      Boolean(value && value.trim().length > 0)
    );
    return titleParts.length > 0 ? `${titleParts.join(" | ")} | ${baseTitle}` : baseTitle;
  }

  if (segments[1] === "audit" && segments[2]) {
    return `Assessment Report | ${baseTitle}`;
  }

  const sectionKey = segments[1] ?? "";
  const humanizedSection = humanizeSegment(sectionKey);
  const sectionLabel =
    DASHBOARD_SEGMENT_LABELS[sectionKey] ?? (humanizedSection || "Workspace Overview");
  return `${sectionLabel} | ${baseTitle}`;
}

export function resolveAlphaColor(color: string, alpha: number): string {
  const normalizedAlpha = clampAlpha(alpha);
  const normalizedColor = color.trim();

  if (HEX_COLOR_PATTERN.test(normalizedColor)) {
    const red = Number.parseInt(normalizedColor.slice(1, 3), 16);
    const green = Number.parseInt(normalizedColor.slice(3, 5), 16);
    const blue = Number.parseInt(normalizedColor.slice(5, 7), 16);
    return `rgba(${red}, ${green}, ${blue}, ${normalizedAlpha})`;
  }

  return `color-mix(in srgb, ${normalizedColor} ${Math.round(normalizedAlpha * 100)}%, transparent)`;
}
