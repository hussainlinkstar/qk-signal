import { requiredPlanLabelForCapability, type PlanCapabilityKey } from "@/lib/planCapabilities";

type PlanLockFeatureKey =
  | "apiAccess"
  | "mcpAccess"
  | "advisorRecommendations"
  | "doneForYouExecution"
  | "competitiveIntelligence"
  | "entities"
  | "entityAuthority"
  | "botLogAnalyzer"
  | "offPageMentions"
  | "aiSearchVolatility"
  | "scheduledAudits"
  | "leads"
  | "battleReports"
  | "brandedReports"
  | "semanticGraph"
  | "brandIntegrity"
  | "whiteLabel";

export type PlanLockContent = {
  requiredPlanLabel: string;
  title: string;
  description: string;
  ctaLabel: string;
  href: string;
  helperText?: string;
};

type PlanLockError = Error & {
  status?: number;
};

const DEFAULT_UPGRADE_HREF = "/dashboard/billing";

/**
 * SIGV2-1221. One spec per lock, and not one hand-written plan name among them.
 *
 * `capabilityKey` is the entitlement the surface is actually gated on, and the
 * plan every line of the card states is derived from it through
 * `MINIMUM_PLAN_BY_FEATURE`. A lock card is a sales promise: naming a plan that
 * does not hold the capability tells a customer to buy something that will not
 * unlock what they just clicked, and naming one they already have tells them to
 * buy what they own. Both were live here before this ticket, because the plan
 * name was copy rather than a computed value.
 *
 * `featureLabel` is the subject of every sentence, so title, CTA and helper
 * text cannot drift apart or name different plans. The shape follows the
 * approved MVP `.lockcard` (`Qiko-Signal-MVP-TBR/mockup/signal.css`): mono plan
 * eyebrow, "<feature> requires <plan>" title, one sentence of what it unlocks,
 * and an "Upgrade to <plan>" CTA. The MVP never prints a price in a lock CTA
 * (`Signal AIO Detail.html`, `Signal SEO Detail.html`, `Signal Gate.html` all
 * say "Upgrade to <plan>" and nothing more), and a price in an upgrade prompt
 * is a second copy of the price list that goes stale the day pricing changes.
 *
 * A capability whose lowest plan is Starter has no lock here at all. Every plan
 * grants it, so there is no plan to upgrade to - the same reason
 * `liveEngineTracking` was removed on SIGV2-1108 and `pdfExports` on this
 * ticket.
 */
type PlanLockSpec = {
  capabilityKey: PlanCapabilityKey;
  featureLabel: string;
  /** True when `featureLabel` takes "require"/"unlock" rather than the -s form. */
  plural?: boolean;
  description: string;
};

const PLAN_LOCK_SPECS: Record<PlanLockFeatureKey, PlanLockSpec> = {
  apiAccess: {
    capabilityKey: "api_access",
    featureLabel: "API & MCP access",
    // SIGV2-1210: the same API key now also opens the MCP server, so an agent
    // such as Claude can read a workspace's visibility data and launch an
    // audit. Named here because this is where a workspace on a lower plan
    // learns what the upgrade actually includes.
    description:
      "Unlock secure API keys, reporting connectors, headless audit delivery, and the MCP server that connects AI agents to this workspace by upgrading.",
  },
  // SIGV2-1210: `mcp_access` is its own entitlement, separate from
  // `api_access`, so the lock derives its plan from that key rather than
  // reusing the API one.
  mcpAccess: {
    capabilityKey: "mcp_access",
    featureLabel: "The MCP server",
    description:
      "Connect Claude, Cursor and other MCP clients to this workspace so agents can read audits, recommendations and competitor data, and start new audits on request.",
  },
  advisorRecommendations: {
    capabilityKey: "has_advisor_recommendations",
    featureLabel: "AI recommendations",
    plural: true,
    description:
      "Unlock the Advisor's full AI action plan: prioritized fixes with the reasoning behind every recommendation, tracked over time.",
  },
  // SIGV2-1168: Jake withdrew done-for-you execution on 6 Oct. The
  // entitlement only unlocks a read-only view of how the Advisor plan
  // evolves across audits - no auto-execution, no CMS/Jira delivery - so the
  // copy describes exactly that and names no price.
  doneForYouExecution: {
    capabilityKey: "has_done_for_you_execution",
    featureLabel: "Advisor plan progress",
    description:
      "See how your Advisor action plan evolves across audits: high-impact fixes resolved, new actions surfaced, and what carried forward.",
  },
  // `liveEngineTracking` was removed in SIGV2-1108: the backend grants
  // `has_live_engine_tracking` to every plan (`CAPABILITY_MATRIX` in
  // `backend/app/config/plans.py`), so there is no plan to upgrade to and
  // nothing to lock.
  competitiveIntelligence: {
    capabilityKey: "has_competitor_analysis",
    featureLabel: "Competitive Intelligence",
    description:
      "Upgrade this workspace to configure competitor benchmarks, recurring refreshes, and AI-backed competitive gap analysis.",
  },
  entities: {
    capabilityKey: "has_entity_enhancement",
    featureLabel: "Entity extraction",
    description:
      "Upgrade this workspace to extract the people, products, and concepts your content is actually recognized for, and how strongly each one is associated with your brand.",
  },
  entityAuthority: {
    capabilityKey: "entity_authority",
    featureLabel: "Entity Authority",
    description:
      "Measure brand-to-entity association strength, surface authority gaps, and monitor trend movement across audits.",
  },
  botLogAnalyzer: {
    capabilityKey: "api_access",
    featureLabel: "The AI bot log analyzer",
    description:
      "Parse server logs, verify bot identity, and track crawl waste with the AI bot log analyzer built for advanced monitoring workflows.",
  },
  offPageMentions: {
    capabilityKey: "api_access",
    featureLabel: "Off-page mention tracking",
    description:
      "Track brand mentions across high-trust corpus domains, sentiment, and entity context from one monitoring surface.",
  },
  aiSearchVolatility: {
    capabilityKey: "api_access",
    featureLabel: "The AI Search Volatility Index",
    description:
      "Correlate project movement with broader AI search turbulence using the volatility index and provider trend overlays.",
  },
  scheduledAudits: {
    capabilityKey: "can_schedule_audits",
    featureLabel: "Scheduled assessments",
    plural: true,
    description:
      "Unlock recurring background audits so your team can monitor changes without relying on manual reruns.",
  },
  leads: {
    capabilityKey: "lead_widget",
    featureLabel: "The Leads dashboard",
    description:
      "Enable embeddable lead capture, widget key management, and inbound audit tracking from one branded workspace.",
  },
  battleReports: {
    capabilityKey: "has_competitor_analysis",
    featureLabel: "Battle reports",
    plural: true,
    description:
      "Unlock competitive battle PDFs that turn benchmark deltas into an executive-ready head-to-head narrative.",
  },
  brandedReports: {
    capabilityKey: "has_advanced_reporting",
    featureLabel: "Branded reports",
    plural: true,
    description:
      "Unlock branded PDFs with advanced reporting so agency teams can package deliverables with stronger presentation control.",
  },
  semanticGraph: {
    capabilityKey: "has_semantic_graph_mapping",
    featureLabel: "Schema coverage insights",
    plural: true,
    description:
      "Unlock semantic graph mapping, schema health analysis, and structured data coverage scoring by upgrading this workspace.",
  },
  brandIntegrity: {
    capabilityKey: "has_brand_integrity_guardrails",
    featureLabel: "Brand integrity guardrails",
    plural: true,
    description:
      "Unlock hallucination detection, claim grounding analysis, and integrity certification for your audit reports.",
  },
  // SIGV2-1039. The backend grants `has_white_label`, `has_custom_domain` and
  // `pdf_white_label` on plan_executive and nowhere else
  // (`MINIMUM_PLAN_BY_FEATURE`), and `_require_workspace_white_label_plan`
  // enforces it with a 402, so Executive is the plan this must name.
  whiteLabel: {
    capabilityKey: "has_white_label",
    featureLabel: "White-label branding",
    description:
      "Put your own brand on the workspace, the client portal and report delivery, and serve it all from your own domain.",
  },
};

/** The entitlement each lock is gated on, exported so tests can pin it. */
export const PLAN_LOCK_CAPABILITY_KEYS: Record<PlanLockFeatureKey, PlanCapabilityKey> =
  Object.fromEntries(
    Object.entries(PLAN_LOCK_SPECS).map(([feature, spec]) => [feature, spec.capabilityKey])
  ) as Record<PlanLockFeatureKey, PlanCapabilityKey>;

const buildPlanLockContent = (spec: PlanLockSpec, planLabel: string): PlanLockContent => ({
  requiredPlanLabel: planLabel,
  title: `${spec.featureLabel} ${spec.plural ? "require" : "requires"} ${planLabel}`,
  description: spec.description,
  ctaLabel: `Upgrade to ${planLabel}`,
  href: DEFAULT_UPGRADE_HREF,
  helperText: `${spec.featureLabel} ${spec.plural ? "unlock" : "unlocks"} on ${planLabel} and above.`,
});

/**
 * Lock copy for a feature, with the plan name derived from the entitlement.
 *
 * A caller that knows the plan the backend actually named for this customer
 * (an audit payload's `required_plan_label`, say) passes it as an override and
 * the whole card is rebuilt around it, so the eyebrow, the title and the CTA
 * can never name three different plans.
 */
export function getPlanLockContent(
  feature: PlanLockFeatureKey,
  overrides: Partial<PlanLockContent> = {}
): PlanLockContent {
  const spec = PLAN_LOCK_SPECS[feature];
  const servedPlanLabel =
    typeof overrides.requiredPlanLabel === "string" ? overrides.requiredPlanLabel.trim() : "";
  const planLabel =
    servedPlanLabel || requiredPlanLabelForCapability(spec.capabilityKey) || "a higher plan";

  const content = buildPlanLockContent(spec, planLabel);

  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    (content as Record<string, unknown>)[key] = value;
  }

  content.requiredPlanLabel = planLabel;
  return content;
}

export function getErrorStatus(error: unknown): number | null {
  if (typeof error === "object" && error !== null && "status" in error) {
    const value = (error as { status?: unknown }).status;
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }

  return null;
}

export function isPlanUpgradeError(error: unknown): error is PlanLockError {
  const status = getErrorStatus(error);
  if (status === 402) {
    return true;
  }

  if (!(error instanceof Error)) {
    return false;
  }

  const message = error.message.toLowerCase();

  // Distinctive enough that the name alone identifies a plan lock. These are the
  // retired tier names, kept so older stored messages still resolve.
  const mentionsDistinctiveTier =
    message.includes("neural core") ||
    message.includes("synapse pro") ||
    message.includes("singularity elite");

  // The current tier names are ordinary English words, so they only count as a
  // plan lock alongside requirement wording. Without that guard, "Executive
  // summary generation failed" would be shown to the user as an upgrade prompt
  // and the real error would be hidden.
  const mentionsCurrentTier =
    message.includes("specialist") ||
    message.includes("executive") ||
    message.includes("agency trial") ||
    message.includes("standard plan") ||
    message.includes("starter plan");

  const mentionsUpgradePath =
    message.includes("current plan") ||
    message.includes("upgrade plan") ||
    message.includes("upgrade your plan") ||
    message.includes("upgrade");
  const mentionsAvailability =
    message.includes("require") ||
    message.includes("available on") ||
    message.includes("available in") ||
    message.includes("included on") ||
    message.includes("not available");

  return (
    mentionsDistinctiveTier ||
    (mentionsCurrentTier && (mentionsUpgradePath || mentionsAvailability)) ||
    ((status === 403 || status === null) && mentionsUpgradePath && mentionsAvailability)
  );
}
