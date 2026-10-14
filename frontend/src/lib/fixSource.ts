import type { FixSource } from "@/lib/reportAdapters";

/**
 * Provenance labels for a consolidated fix row (SIGV2-1193).
 *
 * The product used to show two lists of things to fix, and SIGV2-1175 settled
 * that the customer should be able to tell which was which. Merging them into
 * one ordered list does not withdraw that answer, it moves it onto the row:
 * every row states the channel (or channels) that raised it.
 *
 * One i18n key per source, resolved by the caller, so the chip reads the same
 * on the action plan, the Improve tabs and the audit report.
 */
const SOURCE_KEYS: Record<FixSource, string> = {
  audit_finding: "signalFixes.source.auditFinding",
  action_plan: "signalFixes.source.actionPlan",
};

/** The label keys for a row's sources, in the order the row was sourced. */
export const fixSourceLabelKeys = (sources: readonly FixSource[]): string[] =>
  sources.map((source) => SOURCE_KEYS[source]).filter(Boolean);
