import type { AuditTier } from "@/constants/auditModelMap";

export const ROLE_MODES = ["marketer", "specialist", "agency", "enterprise", "explorer"] as const;
export type RoleMode = (typeof ROLE_MODES)[number];
export const ROLE_LABEL: Record<RoleMode, string> = {
  marketer: "Marketer",
  specialist: "Specialist",
  agency: "Agency",
  enterprise: "Enterprise",
  explorer: "Just exploring",
};

// Mode → canonical section keys that appear in that mode's information
// architecture (from signal_persona_ux_redesign_spec.md §3). Hiding a section
// only removes it from the IA for that mode; it never grants or revokes access.
// Visibility = shownInMode AND roleAllows AND planAllows.
const MODE_SECTIONS: Record<RoleMode, Set<string>> = {
  marketer: new Set(["overview", "aio", "competitors", "recommendations", "reports"]),
  explorer: new Set(["overview", "aio", "recommendations", "reports"]),
  specialist: new Set([
    "overview",
    "seo",
    "aio",
    "aeo",
    "geo",
    "search_types",
    "entities",
    "technical",
    "recommendations",
    "reports",
  ]),
  agency: new Set([
    "overview",
    "portfolio",
    "aio",
    "competitors",
    "recommendations",
    "white_label",
    "reports",
  ]),
  enterprise: new Set([
    "overview",
    "multibrand",
    "aio",
    "competitors",
    "entities",
    "hallucinations",
    "monitoring",
    "audit_trail",
    "recommendations",
    "reports",
  ]),
};

/**
 * Pure resolver: is `section` part of the given role mode's IA?
 * Unknown section keys default to shown so unmapped nav items are never hidden.
 */
export function shownInMode(section: string, mode: RoleMode): boolean {
  return MODE_SECTIONS[mode]?.has(section) ?? true;
}

// Default audit tier suggested for each role mode at first scan
// (signal_persona_role_mode plan, Task 1.8). This is only a DEFAULT the user
// can override; backend plan gating still applies (Starter/Standard = fast only).
const DEFAULT_TIER_BY_ROLE: Record<RoleMode, AuditTier> = {
  marketer: "smart",
  explorer: "fast",
  specialist: "deep_judgment",
  agency: "smart",
  enterprise: "deep_judgment",
};

/**
 * Pure mapping: the default audit tier to pre-select for a given role mode.
 * Does not bypass plan gating — callers must still respect plan/role authz.
 */
export function defaultAuditTierForRole(mode: RoleMode): AuditTier {
  return DEFAULT_TIER_BY_ROLE[mode];
}
