"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { requestJson, requestVoid } from "@/services/http";

export type FeedbackType = "agree" | "disagree" | "fixed";

export type ClaimFeedbackEntry = {
  id: number;
  audit_id: number;
  user_id: number;
  claim_key: string;
  claim_text: string;
  claim_category: string | null;
  feedback_type: FeedbackType;
  feedback_text: string | null;
  created_at: string | null;
};

export type FeedbackSummary = Record<string, { agree: number; disagree: number; fixed: number }>;

export function useClaimFeedback(auditId: string | number | null) {
  const [myFeedback, setMyFeedback] = useState<ClaimFeedbackEntry[]>([]);
  const [summary, setSummary] = useState<FeedbackSummary>({});
  const [loading, setLoading] = useState(false);
  const fetchedRef = useRef(false);

  const load = useCallback(async () => {
    if (!auditId) return;
    setLoading(true);
    try {
      const [mine, sum] = await Promise.all([
        requestJson<ClaimFeedbackEntry[]>({
          endpoint: `/api/audits/${auditId}/feedback?mine_only=true`,
          method: "GET",
          errorMessage: "Failed to load claim feedback",
        }),
        requestJson<FeedbackSummary>({
          endpoint: `/api/audits/${auditId}/feedback/summary`,
          method: "GET",
          errorMessage: "Failed to load feedback summary",
        }),
      ]);
      setMyFeedback(mine);
      setSummary(sum);
    } catch {
      /* silently degrade */
    } finally {
      setLoading(false);
    }
  }, [auditId]);

  useEffect(() => {
    if (!fetchedRef.current && auditId) {
      fetchedRef.current = true;
      load();
    }
  }, [auditId, load]);

  const submit = useCallback(
    async (params: {
      claimKey: string;
      claimText: string;
      claimCategory: string | null;
      feedbackType: FeedbackType;
      feedbackText?: string | null;
    }) => {
      if (!auditId) return;
      const res = await requestJson<ClaimFeedbackEntry>({
        endpoint: `/api/audits/${auditId}/feedback`,
        method: "POST",
        body: {
          claim_key: params.claimKey,
          claim_text: params.claimText,
          claim_category: params.claimCategory,
          feedback_type: params.feedbackType,
          feedback_text: params.feedbackText || null,
        },
        errorMessage: "Failed to submit claim feedback",
      });
      setMyFeedback((prev) => {
        const filtered = prev.filter((f) => f.claim_key !== params.claimKey);
        return [...filtered, res];
      });
      setSummary((prev) => {
        const existing = prev[params.claimKey] || {
          agree: 0,
          disagree: 0,
          fixed: 0,
        };
        const oldEntry = myFeedback.find((f) => f.claim_key === params.claimKey);
        const updated = { ...existing };
        if (oldEntry) {
          updated[oldEntry.feedback_type] = Math.max(0, updated[oldEntry.feedback_type] - 1);
        }
        updated[params.feedbackType] = (updated[params.feedbackType] || 0) + 1;
        return { ...prev, [params.claimKey]: updated };
      });
      return res;
    },
    [auditId, myFeedback]
  );

  const remove = useCallback(
    async (feedbackId: number, claimKey: string) => {
      if (!auditId) return;
      await requestVoid({
        endpoint: `/api/audits/${auditId}/feedback/${feedbackId}`,
        method: "DELETE",
        errorMessage: "Failed to delete claim feedback",
      });
      const removed = myFeedback.find((f) => f.id === feedbackId);
      setMyFeedback((prev) => prev.filter((f) => f.id !== feedbackId));
      if (removed) {
        setSummary((prev) => {
          const existing = prev[claimKey] || {
            agree: 0,
            disagree: 0,
            fixed: 0,
          };
          return {
            ...prev,
            [claimKey]: {
              ...existing,
              [removed.feedback_type]: Math.max(0, existing[removed.feedback_type] - 1),
            },
          };
        });
      }
    },
    [auditId, myFeedback]
  );

  const getMyFeedback = useCallback(
    (claimKey: string): ClaimFeedbackEntry | undefined =>
      myFeedback.find((f) => f.claim_key === claimKey),
    [myFeedback]
  );

  const getSummary = useCallback((claimKey: string) => summary[claimKey] || null, [summary]);

  return { loading, myFeedback, summary, submit, remove, getMyFeedback, getSummary, reload: load };
}
