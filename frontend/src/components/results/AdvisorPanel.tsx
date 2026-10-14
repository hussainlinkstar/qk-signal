"use client";

import React from "react";
import { Check, ChevronRight, Gauge, Loader2, TrendingUp, X } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/custom-auth";
import { cx } from "@/components/ui/utils";
import GatedSection from "@/components/results/GatedSection";
import { minimumPlanForCapability, requiredPlanLabelForCapability } from "@/lib/planCapabilities";
import type { AdvisorLevel, ConsolidatedFix, ResolvedLevel } from "@/lib/reportAdapters";
import { fixSourceLabelKeys } from "@/lib/fixSource";
import {
  recordRecommendationDecision,
  type RecommendationDecisionType,
} from "@/services/learningsService";

// The Advisor is the `has_advisor_recommendations` entitlement, so the plan
// this upsell names comes from that capability (SIGV2-1221).
const ADVISOR_REQUIRED_PLAN = minimumPlanForCapability("has_advisor_recommendations") ?? "";
const ADVISOR_REQUIRED_PLAN_LABEL =
  requiredPlanLabelForCapability("has_advisor_recommendations") ?? "a higher plan";

type AdvisorPanelProps = {
  /**
   * The single consolidated fix list (SIGV2-1193), or `null`/empty when the
   * audit produced nothing to act on. This used to be the Advisor plan alone,
   * which meant this panel and the report's own fix rows counted different
   * lists.
   */
  fixes: ConsolidatedFix[] | null;
  /**
   * When `true`, the panel preview is blurred behind a `GatedSection` upsell.
   * The actual plan-tier gating is wired in Phase 5 — this just passes through.
   */
  isLocked?: boolean;
  /** Optional guest-audit token forwarded to the gated upsell CTA. */
  guestAuditToken?: string;
  /**
   * The owning project's id. When present (and the panel is unlocked) each
   * action gains accept/dismiss controls wired to the learnings loop. Absent
   * for guest audits — the controls stay hidden so guest callers are unaffected.
   */
  projectId?: string | number | null;
  className?: string;
};

const IMPACT_CHIP: Record<AdvisorLevel, string> = {
  high: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  low: "border-(--line) bg-(--line-2) text-(--t-2)",
};

const IMPACT_LABEL: Record<AdvisorLevel, string> = {
  high: "High lift",
  medium: "Medium lift",
  low: "Low lift",
};

const EFFORT_CHIP: Record<AdvisorLevel, string> = {
  low: "border-(--line) bg-(--line-2) text-(--t-2)",
  medium: "border-(--line) bg-(--line-2) text-(--t-2)",
  high: "border-(--line) bg-(--line-2) text-(--t-2)",
};

const EFFORT_LABEL: Record<AdvisorLevel, string> = {
  low: "Low effort",
  medium: "Medium effort",
  high: "High effort",
};

// SIGV2-1193 / SIGV2-1211: an unmeasured rating is a state, not a band. This
// panel used to read `action.impact` and `action.effort` straight off the
// Advisor payload, where both are silently defaulted to "medium", so it
// showed "Medium lift" for fixes nothing had rated. The dashed chip says so
// instead.
const UNRATED_CHIP = "border-dashed border-(--line) bg-transparent text-(--t-3)";

const levelChip = (level: ResolvedLevel, chips: Record<AdvisorLevel, string>): string =>
  level.measured ? chips[level.level] : UNRATED_CHIP;

const levelLabel = (
  level: ResolvedLevel,
  labels: Record<AdvisorLevel, string>,
  unrated: string
): string => (level.measured ? labels[level.level] : unrated);

/** This panel predates the i18n catalogue and renders literal copy. */
const SOURCE_TEXT: Record<string, string> = {
  "signalFixes.source.auditFinding": "From the audit",
  "signalFixes.source.actionPlan": "From your action plan",
};

/** The raw action text the backend hashes into the decision fingerprint. */
const actionTextFor = (fix: ConsolidatedFix): string => fix.actionText ?? fix.title;

/**
 * Sent alongside the text so a deterministic action's decision is keyed on the
 * failing check rather than on wording the LLM rewrites each audit; `null`
 * falls back to text identity (SIGV2-1118).
 */
const problemCodeFor = (fix: ConsolidatedFix): string | null => fix.problemCode ?? null;

type AdvisorFixRowProps = {
  fix: ConsolidatedFix;
  /** When `true`, accept/dismiss controls render for this row. */
  showControls: boolean;
  /** `accepted` once the user accepts this fix; `null` while undecided. */
  accepted: boolean;
  /** `true` while a decision request for this row is in flight. */
  submitting: boolean;
  onDecision: (fix: ConsolidatedFix, decision: RecommendationDecisionType) => void;
};

const AdvisorFixRow = ({
  fix,
  showControls,
  accepted,
  submitting,
  onDecision,
}: AdvisorFixRowProps) => {
  const { rank, title, description, impactLevel, effortLevel } = fix;
  return (
    <li className="relative flex gap-4 rounded border border-(--line) bg-(--line-2) p-4 shadow-inner transition-colors hover:bg-(--line-2)">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-primary/[0.08] text-xs font-black text-primary">
        {rank}
      </div>
      <div className="flex-1 space-y-2">
        <p className="text-sm font-semibold leading-snug text-(--t-1)">{title}</p>
        {description && <p className="text-xs leading-relaxed text-(--t-2)">{description}</p>}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span
            className={cx(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
              levelChip(impactLevel, IMPACT_CHIP)
            )}
          >
            <TrendingUp className="h-3 w-3" />
            {levelLabel(impactLevel, IMPACT_LABEL, "Impact not rated")}
          </span>
          <span
            className={cx(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
              levelChip(effortLevel, EFFORT_CHIP)
            )}
          >
            <Gauge className="h-3 w-3" />
            {levelLabel(effortLevel, EFFORT_LABEL, "Effort not rated")}
          </span>
          {/* SIGV2-1193: which channel raised this row. */}
          {fixSourceLabelKeys(fix.sources).map((key) => (
            <span
              key={key}
              className="inline-flex items-center gap-1 rounded-full border border-(--line) bg-(--paper) px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-(--t-3)"
            >
              {SOURCE_TEXT[key] ?? key}
            </span>
          ))}
        </div>
        {showControls && (
          <div className="flex flex-wrap items-center gap-2 pt-2">
            {accepted ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-300">
                <Check className="h-3 w-3" />
                Accepted
              </span>
            ) : (
              <button
                type="button"
                disabled={submitting}
                onClick={() => onDecision(fix, "accepted")}
                aria-label={`Accept recommendation: ${title}`}
                className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-300 transition-colors hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Check className="h-3 w-3" />
                )}
                Accept
              </button>
            )}
            <button
              type="button"
              disabled={submitting}
              onClick={() => onDecision(fix, "dismissed")}
              aria-label={`Dismiss recommendation: ${title}`}
              className="inline-flex items-center gap-1 rounded-full border border-(--line) bg-(--line-2) px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-(--t-2) transition-colors hover:border-rose-500/30 hover:bg-rose-500/10 hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <X className="h-3 w-3" />
              )}
              Dismiss
            </button>
          </div>
        )}
      </div>
    </li>
  );
};

type AdvisorPanelBodyProps = {
  fixes: ConsolidatedFix[];
  projectId?: string | number | null;
};

const AdvisorPanelBody = ({ fixes, projectId }: AdvisorPanelBodyProps) => {
  const { getToken } = useAuth();
  const showControls = projectId !== null && projectId !== undefined && projectId !== "";

  const [dismissedIds, setDismissedIds] = React.useState<ReadonlySet<string>>(new Set());
  const [acceptedIds, setAcceptedIds] = React.useState<ReadonlySet<string>>(new Set());
  const [submittingId, setSubmittingId] = React.useState<string | null>(null);

  const handleDecision = React.useCallback(
    async (fix: ConsolidatedFix, decision: RecommendationDecisionType) => {
      if (!showControls || projectId === null || projectId === undefined) {
        return;
      }
      setSubmittingId(fix.id);
      try {
        const token = await getToken();
        const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
        await recordRecommendationDecision(
          projectId,
          {
            action_text: actionTextFor(fix),
            problem_code: problemCodeFor(fix),
            decision,
          },
          headers
        );
        if (decision === "dismissed") {
          setDismissedIds((current) => new Set(current).add(fix.id));
          toast.success("Recommendation dismissed. It won't appear on future audits.");
        } else {
          setAcceptedIds((current) => new Set(current).add(fix.id));
          toast.success("Recommendation accepted.");
        }
      } catch (decisionError) {
        toast.error(
          decisionError instanceof Error
            ? decisionError.message
            : "Unable to record recommendation decision."
        );
      } finally {
        setSubmittingId(null);
      }
    },
    [getToken, projectId, showControls]
  );

  const visibleFixes = fixes.filter((fix) => !dismissedIds.has(fix.id));

  return (
    <div className="space-y-6" data-testid="advisor-panel">
      <div className="space-y-1">
        <h3 className="flex items-center gap-3 text-sm font-black uppercase tracking-[0.2em] text-(--t-1)">
          <ChevronRight className="h-4 w-4 text-primary" />
          What to fix, in order
        </h3>
        <p className="pl-7 text-xs font-medium text-(--t-3)">
          ROI-ranked, biggest and easiest wins first
        </p>
      </div>
      <ol className="space-y-3">
        {visibleFixes.map((fix) => (
          <AdvisorFixRow
            key={fix.id}
            fix={fix}
            showControls={showControls}
            accepted={acceptedIds.has(fix.id)}
            submitting={submittingId === fix.id}
            onDecision={handleDecision}
          />
        ))}
      </ol>
    </div>
  );
};

/**
 * Presentational ROI-ranked fix panel ("What to fix, in order").
 *
 * SIGV2-1193: this renders the single consolidated fix list, not the Advisor
 * plan on its own. The plan is one of that list's two input channels (the
 * other is the audit's own findings), and showing only one of them here while
 * the report's fix rows showed the merge is exactly the disagreement this
 * ticket removes. Renders nothing when there is no fix to show. When
 * `isLocked` is `true`, the panel is shown blurred behind a `GatedSection`
 * upsell.
 *
 * When `projectId` is supplied and the panel is unlocked, each row exposes
 * accept/dismiss controls wired to the learnings loop (Task 7.3): dismissing a
 * fix removes it from the current view and suppresses it on future audits.
 */
export default function AdvisorPanel({
  fixes,
  isLocked = false,
  guestAuditToken,
  projectId,
  className,
}: AdvisorPanelProps) {
  if (!fixes || fixes.length === 0) {
    return null;
  }

  if (isLocked) {
    return (
      <div className={className}>
        <GatedSection
          title="What to fix, in order"
          teaser="Your ROI-ranked action plan: the biggest, easiest wins first, grounded in your audit findings."
          requiredPlan={ADVISOR_REQUIRED_PLAN}
          requiredPlanLabel={ADVISOR_REQUIRED_PLAN_LABEL}
          guestAuditToken={guestAuditToken}
          blurredPreview={<AdvisorPanelBody fixes={fixes} />}
          features={[
            "Every action ranked by ROI, biggest wins first",
            "Accept or dismiss each recommendation",
            "Grounded in this audit's actual findings, not generic advice",
          ]}
        />
      </div>
    );
  }

  return (
    <div className={className}>
      <AdvisorPanelBody fixes={fixes} projectId={projectId} />
    </div>
  );
}
