"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React from "react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2, MessageSquareQuote } from "lucide-react";

import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import Button from "@/components/ui/Button";

type TrialFeedbackRequest = {
  token: string;
  status: "pending" | "submitted" | "expired";
  recipient_email: string;
  recipient_name: string;
  requested_by_name: string;
  trigger_reason: string;
  trial_started_at: string | null;
  trial_ended_at: string | null;
  expires_at: string | null;
  submitted_at: string | null;
};

const triggerReasonCopy: Record<string, string> = {
  trial_expired: "Your trial period reached its scheduled end.",
  credits_exhausted: "Your trial used the included capacity.",
  audits_exhausted: "Your trial used the included audit capacity.",
  trial_completed: "Your trial period concluded.",
};

export default function TrialFeedbackPage() {
  const params = useParams<{ token: string }>();
  const token = Array.isArray(params?.token) ? params.token[0] : params?.token;

  const [requestData, setRequestData] = useState<TrialFeedbackRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [overallRating, setOverallRating] = useState<number>(0);
  const [wouldRecommend, setWouldRecommend] = useState<"yes" | "maybe" | "no">("yes");
  const [whatWorkedWell, setWhatWorkedWell] = useState("");
  const [whatWasMissing, setWhatWasMissing] = useState("");
  const [improvementSuggestions, setImprovementSuggestions] = useState("");

  useEffect(() => {
    if (!token) {
      setError("This feedback link is invalid.");
      setLoading(false);
      return;
    }

    let cancelled = false;
    const loadRequest = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`/api/trial-feedback/${encodeURIComponent(token)}`, {
          method: "GET",
          headers: {
            "X-Request-ID": `trial-feedback:${token}`,
          },
        });
        if (!response.ok) {
          throw new Error("This feedback link is no longer available.");
        }
        const payload = (await response.json()) as TrialFeedbackRequest;
        if (!cancelled) {
          setRequestData(payload);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unable to load this feedback request.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadRequest();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const statusCopy = useMemo(() => {
    if (!requestData) {
      return null;
    }
    if (requestData.status === "submitted") {
      return "Feedback already received. Thank you for helping shape the product.";
    }
    if (requestData.status === "expired") {
      return "This secure feedback link has expired.";
    }
    return triggerReasonCopy[requestData.trigger_reason] || triggerReasonCopy.trial_completed;
  }, [requestData]);

  const handleSubmit = async () => {
    if (!token) {
      setError("This feedback link is invalid.");
      return;
    }
    if (overallRating < 1 || overallRating > 5) {
      setError("Please choose an overall rating before submitting.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/trial-feedback/${encodeURIComponent(token)}/submit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": `trial-feedback-submit:${token}`,
        },
        body: JSON.stringify({
          overall_rating: overallRating,
          would_recommend: wouldRecommend,
          what_worked_well: whatWorkedWell.trim() || null,
          what_was_missing: whatWasMissing.trim() || null,
          improvement_suggestions: improvementSuggestions.trim() || null,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(
          typeof payload.detail === "string" ? payload.detail : "Unable to submit feedback."
        );
      }
      const payload = (await response.json()) as {
        status: "submitted";
        submitted_at: string | null;
      };
      setRequestData((current) =>
        current
          ? {
              ...current,
              status: payload.status,
              submitted_at: payload.submitted_at,
            }
          : current
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to submit feedback.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main
      id="main-content"
      className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(79,70,229,0.18),transparent_28%),radial-gradient(circle_at_80%_20%,rgba(6,182,212,0.2),transparent_32%),#09090B] px-4 py-10 text-(--foreground) sm:px-6"
    >
      <div className="mx-auto max-w-3xl">
        <div className="mb-8 flex items-center justify-center">
          <SignalBrandLockup />
        </div>

        <section className="overflow-hidden rounded-[10px] border border-white/10 bg-[#111317]/90 shadow-[0_28px_90px_rgba(0,0,0,0.45)]">
          <div className="border-b   px-6 py-6 sm:px-8">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full border border-brand-geo/30 bg-brand-geo/10 text-brand-geo">
                <MessageSquareQuote className="h-6 w-6" />
              </div>
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">
                  Trial Feedback
                </p>
                <h1 className="text-3xl font-semibold tracking-tight text-white">
                  Tell us how the trial felt
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-slate-300">
                  Your feedback goes directly into future product improvements, onboarding changes,
                  and roadmap prioritization.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-6 px-6 py-6 sm:px-8 sm:py-8">
            {loading ? (
              <div className="flex min-h-[280px] items-center justify-center gap-3 text-sm text-slate-300">
                <Loader2 className="h-5 w-5 animate-spin text-brand-geo" />
                Loading secure feedback request...
              </div>
            ) : error ? (
              <SignalAlert tone="danger" title="Feedback request failed">
                {error}
              </SignalAlert>
            ) : requestData ? (
              <>
                <div className="grid gap-4 rounded-[10px] border  bg-black/20 p-5 sm:grid-cols-2">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-slate-500">
                      Requested By
                    </p>
                    <p className="mt-2 text-sm font-medium text-white">
                      {requestData.requested_by_name}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-slate-500">
                      Feedback For
                    </p>
                    <p className="mt-2 text-sm font-medium text-white">
                      {requestData.recipient_email}
                    </p>
                  </div>
                  <div className="sm:col-span-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-slate-500">
                      Trial Status
                    </p>
                    <p className="mt-2 text-sm text-slate-300">{statusCopy}</p>
                  </div>
                </div>

                {requestData.status === "submitted" ? (
                  <SignalAlert tone="success" title="Feedback received">
                    Thank you. This response is now attached to your trial record and can be used by
                    the team to improve onboarding, output quality, and product depth.
                  </SignalAlert>
                ) : requestData.status === "expired" ? (
                  <SignalAlert tone="warning" title="Link expired">
                    This secure feedback link is no longer active. If feedback is still needed, the
                    team can issue a fresh request.
                  </SignalAlert>
                ) : (
                  <div className="space-y-6">
                    <section className="space-y-3">
                      <label className="text-sm font-medium text-white">Overall rating</label>
                      <div className="flex flex-wrap gap-2">
                        {[1, 2, 3, 4, 5].map((value) => (
                          <button
                            key={value}
                            type="button"
                            onClick={() => setOverallRating(value)}
                            className={`flex h-12 w-12 items-center justify-center rounded-full border text-sm font-semibold transition ${
                              overallRating === value
                                ? "border-brand-geo bg-brand-geo text-white"
                                : "border-white/10  text-slate-300 hover:border-brand-geo/50 hover:text-white"
                            }`}
                            aria-label={`Rate ${value} out of 5`}
                          >
                            {value}
                          </button>
                        ))}
                      </div>
                    </section>

                    <section className="space-y-3">
                      <label htmlFor="would-recommend" className="text-sm font-medium text-white">
                        Would you recommend the product?
                      </label>
                      <select
                        id="would-recommend"
                        value={wouldRecommend}
                        onChange={(event) =>
                          setWouldRecommend(event.target.value as "yes" | "maybe" | "no")
                        }
                        className="h-12 w-full rounded-[10px] border border-white/10 bg-black/30 px-4 text-sm text-white outline-hidden transition focus:border-brand-geo/60"
                      >
                        <option value="yes">Yes</option>
                        <option value="maybe">Maybe</option>
                        <option value="no">No</option>
                      </select>
                    </section>

                    <section className="space-y-3">
                      <label htmlFor="worked-well" className="text-sm font-medium text-white">
                        What worked well?
                      </label>
                      <textarea
                        id="worked-well"
                        value={whatWorkedWell}
                        onChange={(event) => setWhatWorkedWell(event.target.value)}
                        rows={4}
                        className="w-full rounded-[10px] border border-white/10 bg-black/30 px-4 py-3 text-sm text-white outline-hidden transition placeholder:text-slate-500 focus:border-brand-geo/60"
                        placeholder="What delivered value quickly for your team?"
                      />
                    </section>

                    <section className="space-y-3">
                      <label htmlFor="missing" className="text-sm font-medium text-white">
                        What felt missing or confusing?
                      </label>
                      <textarea
                        id="missing"
                        value={whatWasMissing}
                        onChange={(event) => setWhatWasMissing(event.target.value)}
                        rows={4}
                        className="w-full rounded-[10px] border border-white/10 bg-black/30 px-4 py-3 text-sm text-white outline-hidden transition placeholder:text-slate-500 focus:border-brand-geo/60"
                        placeholder="Missing workflows, unclear UX, output gaps, pricing friction..."
                      />
                    </section>

                    <section className="space-y-3">
                      <label htmlFor="improvements" className="text-sm font-medium text-white">
                        What should we improve next?
                      </label>
                      <textarea
                        id="improvements"
                        value={improvementSuggestions}
                        onChange={(event) => setImprovementSuggestions(event.target.value)}
                        rows={4}
                        className="w-full rounded-[10px] border border-white/10 bg-black/30 px-4 py-3 text-sm text-white outline-hidden transition placeholder:text-slate-500 focus:border-brand-geo/60"
                        placeholder="What would make you come back, expand usage, or upgrade?"
                      />
                    </section>

                    {error ? (
                      <SignalAlert tone="danger" title="Feedback request failed">
                        {error}
                      </SignalAlert>
                    ) : null}

                    <div className="flex justify-end">
                      <Button
                        variant="primary"
                        size="lg"
                        onClick={handleSubmit}
                        loading={submitting}
                        loadingText="Submitting..."
                        className="min-w-[180px] rounded-[10px]"
                      >
                        Submit Feedback
                      </Button>
                    </div>
                  </div>
                )}
              </>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
