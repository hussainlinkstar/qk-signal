"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Check, Loader2, X } from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import { cx } from "@/components/ui/utils";
import { formatDateTime } from "@/lib/dateFormat";
import {
  fetchRecommendationDecisions,
  type RecommendationDecision,
} from "@/services/learningsService";

type LearningsViewProps = {
  projectId: string;
};

const DECISION_LABEL: Record<RecommendationDecision["decision"], string> = {
  accepted: "Accepted",
  dismissed: "Dismissed",
};

const DECISION_TONE: Record<RecommendationDecision["decision"], string> = {
  accepted: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  dismissed: "border-rose-500/30 bg-rose-500/10 text-rose-300",
};

/**
 * Read-only history of the accept/dismiss decisions a project has recorded for
 * Advisor recommendations (Task 7.3 learnings loop). Dismissed actions are
 * suppressed from future audits; this surface keeps the audit trail visible.
 */
export default function LearningsView({ projectId }: LearningsViewProps) {
  const { getToken, isLoading: authLoading, isSignedIn } = useAuth();

  const [loading, setLoading] = useState(true);
  const [decisions, setDecisions] = useState<RecommendationDecision[]>([]);
  const [error, setError] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to view recommendation learnings.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadDecisions = useCallback(async () => {
    if (!projectId || authLoading) {
      return;
    }
    if (!isSignedIn) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const rows = await fetchRecommendationDecisions(projectId, headers);
      setDecisions(rows);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "Unable to load recommendation learnings."
      );
    } finally {
      setLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, projectId]);

  useEffect(() => {
    void loadDecisions();
  }, [loadDecisions]);

  const shellCls = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";

  if (authLoading || loading) {
    return (
      <section className={shellCls}>
        <div className="flex items-center gap-3 text-[13px] text-(--t-3)">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading recommendation learnings...
        </div>
      </section>
    );
  }

  if (!isSignedIn) {
    return (
      <section className={shellCls}>
        <p className="m-0 text-[13px] text-(--t-3)">
          Sign in to review the accept/dismiss history for this project.
        </p>
      </section>
    );
  }

  return (
    <section className={shellCls} data-testid="learnings-view">
      {/* Approved `.wsec` head. */}
      <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
        Learnings
      </h3>
      <p className="mt-1 text-[12.5px] leading-[1.5] text-(--t-3)">
        Every Advisor recommendation you accept or dismiss is recorded here. Dismissed
        recommendations are suppressed from future audits.
      </p>

      {error ? (
        <p className="mt-3 text-[12px] text-(--bad)" role="alert">
          {error}
        </p>
      ) : null}

      <div className="mt-4 space-y-3">
        {decisions.length === 0 ? (
          <div className="rounded-[14px] border border-dashed border-[#D1D5DB] bg-[#F8FAFC] px-4 py-[26px] text-center text-[13px] text-(--t-3)">
            No learnings yet.
          </div>
        ) : (
          decisions.map((decision) => (
            <div
              key={decision.id}
              data-testid="learnings-row"
              className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={cx(
                    "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em]",
                    DECISION_TONE[decision.decision]
                  )}
                >
                  {decision.decision === "accepted" ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    <X className="h-3 w-3" />
                  )}
                  {DECISION_LABEL[decision.decision]}
                </span>
                {decision.created_at ? (
                  <span className="text-xs text-(--text-muted)">
                    {formatDateTime(decision.created_at)}
                  </span>
                ) : null}
              </div>
              {decision.action_label ? (
                <p className="mt-2 text-sm font-medium text-(--foreground)">
                  {decision.action_label}
                </p>
              ) : (
                <p className="mt-2 break-all font-mono text-xs text-(--text-muted)">
                  {decision.action_fingerprint.slice(0, 12)}
                </p>
              )}
              {decision.note ? (
                <p className="mt-2 text-sm text-(--text-soft)">{decision.note}</p>
              ) : null}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
