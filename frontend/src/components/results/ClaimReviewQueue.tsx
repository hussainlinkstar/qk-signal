"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Filter, ShieldAlert, XCircle } from "lucide-react";
import { toast } from "sonner";

import { ClientSafeDate } from "@/lib/dateFormat";
import EmptyState from "@/components/ui/EmptyState";
import Button from "@/components/ui/Button";
import SelectField from "@/components/ui/SelectField";
import TextAreaField from "@/components/ui/TextAreaField";
import { Spinner } from "@/components/ui/Loading";
import { cx } from "@/components/ui/utils";
import {
  fetchClaimReviewQueue,
  submitClaimReview,
  type ClaimReviewDisposition,
  type ClaimReviewDomainFilter,
  type ClaimReviewQueueItem,
  type ClaimReviewQueueResponse,
  type ClaimReviewStatusFilter,
  type ClaimReviewSummaryResponse,
} from "@/services/claimReviewService";

type ClaimReviewQueueProps = {
  auditId: number;
  getAuthHeaders: () => Promise<Record<string, string>>;
  onSummaryChange?: (summary: ClaimReviewSummaryResponse) => void;
};

function toSummary(queue: ClaimReviewQueueResponse): ClaimReviewSummaryResponse {
  return {
    audit_id: queue.audit_id,
    total_flagged: queue.total_flagged,
    approved_count: queue.approved_count,
    refused_count: queue.refused_count,
    pending_count: queue.pending,
    impact: {
      score_recalculated: false,
      export_excluded_claims: queue.refused_count,
      note: "Refused claims are excluded from export-safe integrity summaries; audit scores are not recalculated automatically.",
    },
  };
}

function statusFilterForClaim(claim: ClaimReviewQueueItem): ClaimReviewStatusFilter {
  if (claim.current_disposition === "manually_approved") return "approved";
  if (claim.current_disposition === "manually_refused") return "refused";
  return "pending";
}

function formatDispositionLabel(value: ClaimReviewQueueItem["current_disposition"]): string {
  if (value === "manually_approved") return "Approved";
  if (value === "manually_refused") return "Refused";
  return "Pending Review";
}

function formatBandLabel(value: string | null): string {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function dispositionTone(value: ClaimReviewQueueItem["current_disposition"]): string {
  if (value === "manually_approved") {
    return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
  }
  if (value === "manually_refused") {
    return "border-rose-500/30 bg-rose-500/10 text-rose-200";
  }
  return "border-amber-500/30 bg-amber-500/10 text-amber-100";
}

function bandTone(value: string | null): string {
  if (value === "high") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
  if (value === "medium") return "border-sky-500/30 bg-sky-500/10 text-sky-100";
  return "border-amber-500/30 bg-amber-500/10 text-amber-100";
}

function formatEvidenceAnchor(value: Record<string, unknown> | null): string[] {
  if (!value) return [];

  const lines: string[] = [];
  const scores = value.scores;
  if (scores && typeof scores === "object" && !Array.isArray(scores)) {
    Object.entries(scores).forEach(([key, item]) => {
      if (typeof item === "number") {
        lines.push(`${key.toUpperCase()}: ${Math.round(item)}`);
      }
    });
  }

  const criticalMetrics = value.critical_metrics;
  if (criticalMetrics && typeof criticalMetrics === "object" && !Array.isArray(criticalMetrics)) {
    Object.entries(criticalMetrics).forEach(([key, item]) => {
      if (typeof item === "number" || typeof item === "string") {
        lines.push(`${key.replace(/_/g, " ")}: ${item}`);
      }
    });
  }

  if (lines.length === 0) {
    Object.entries(value).forEach(([key, item]) => {
      if (typeof item === "number" || typeof item === "string") {
        lines.push(`${key.replace(/_/g, " ")}: ${item}`);
      }
    });
  }

  return lines.slice(0, 5);
}

export default function ClaimReviewQueue({
  auditId,
  getAuthHeaders,
  onSummaryChange,
}: ClaimReviewQueueProps) {
  const [queue, setQueue] = useState<ClaimReviewQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [domainFilter, setDomainFilter] = useState<ClaimReviewDomainFilter>("all");
  const [statusFilter, setStatusFilter] = useState<ClaimReviewStatusFilter>("all");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [submittingClaimId, setSubmittingClaimId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadQueue() {
      setLoading(true);
      setError(null);
      try {
        const headers = await getAuthHeaders();
        const response = await fetchClaimReviewQueue(auditId, headers);
        if (cancelled) {
          return;
        }
        setQueue(response);
        setNotes((current) => {
          const next = { ...current };
          response.claims.forEach((claim) => {
            const existing = current[claim.claim_id];
            next[claim.claim_id] =
              typeof existing === "string" && existing.length > 0
                ? existing
                : (claim.review_decision?.review_note ?? "");
          });
          return next;
        });
        onSummaryChange?.(toSummary(response));
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        setError(
          loadError instanceof Error ? loadError.message : "Unable to load the review queue."
        );
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadQueue();
    return () => {
      cancelled = true;
    };
  }, [auditId, getAuthHeaders, onSummaryChange]);

  async function refreshQueue() {
    const headers = await getAuthHeaders();
    const response = await fetchClaimReviewQueue(auditId, headers);
    setQueue(response);
    setNotes((current) => {
      const next = { ...current };
      response.claims.forEach((claim) => {
        next[claim.claim_id] = claim.review_decision?.review_note ?? current[claim.claim_id] ?? "";
      });
      return next;
    });
    onSummaryChange?.(toSummary(response));
  }

  async function handleReview(claim: ClaimReviewQueueItem, disposition: ClaimReviewDisposition) {
    const label = disposition === "manually_approved" ? "approve" : "refuse";
    if (!window.confirm(`Do you want to ${label} claim ${claim.claim_id}?`)) {
      return;
    }

    setSubmittingClaimId(claim.claim_id);
    try {
      const headers = await getAuthHeaders();
      await submitClaimReview(
        auditId,
        claim.claim_id,
        {
          disposition,
          note: notes[claim.claim_id]?.trim() || null,
        },
        headers
      );
      toast.success(
        disposition === "manually_approved"
          ? "Claim approved and marked as verified."
          : "Claim refused and excluded from export-safe review summaries."
      );
      await refreshQueue();
    } catch (submitError) {
      toast.error(
        submitError instanceof Error
          ? submitError.message
          : "Unable to save the claim review decision."
      );
    } finally {
      setSubmittingClaimId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[280px] items-center justify-center rounded border border-(--border) bg-(--surface-subtle)">
        <Spinner size="md" label="Loading claim review queue" />
      </div>
    );
  }

  if (error) {
    return <EmptyState icon={ShieldAlert} title="Review queue unavailable" description={error} />;
  }

  if (!queue || queue.total_flagged === 0) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="No claim review required"
        description="This audit does not contain any Track B claims waiting for manual disposition."
      />
    );
  }

  const filteredClaims = queue.claims.filter((claim) => {
    const matchesDomain = domainFilter === "all" || claim.domain === domainFilter;
    const matchesStatus = statusFilter === "all" || statusFilterForClaim(claim) === statusFilter;
    return matchesDomain && matchesStatus;
  });

  return (
    <div className="space-y-6">
      <div className="rounded border border-(--border) bg-(--surface-subtle) p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.24em] text-(--text-muted)">
              <Filter className="h-3.5 w-3.5 text-primary" />
              Review Queue
            </div>
            <h2 className="text-xl font-semibold text-(--foreground)">
              {queue.pending} pending / {queue.total_flagged} total
            </h2>
            <p className="text-sm text-(--text-muted)">
              Approved claims stay in the report. Refused claims stay in the audit trail but are
              excluded from export-safe integrity summaries.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:min-w-[360px]">
            <SelectField
              aria-label="Filter review queue by domain"
              label="Domain"
              value={domainFilter}
              onChange={(event) => setDomainFilter(event.target.value as ClaimReviewDomainFilter)}
            >
              <option value="all">All domains</option>
              <option value="seo">SEO</option>
              <option value="geo">AI visibility</option>
              <option value="aeo">AI answers</option>
              <option value="general">General</option>
            </SelectField>
            <SelectField
              aria-label="Filter review queue by status"
              label="Status"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as ClaimReviewStatusFilter)}
            >
              <option value="all">All statuses</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="refused">Refused</option>
            </SelectField>
          </div>
        </div>
      </div>

      {filteredClaims.length === 0 ? (
        <EmptyState
          icon={AlertTriangle}
          title="No claims match the current filters"
          description="Adjust the domain or status filters to inspect the remaining review queue."
        />
      ) : null}

      {filteredClaims.map((claim) => {
        const evidenceLines = formatEvidenceAnchor(claim.evidence_anchor_excerpt);
        const isSubmitting = submittingClaimId === claim.claim_id;
        const reviewedBy = claim.review_decision?.reviewed_by_display_name;
        const reviewedAt = claim.review_decision?.reviewed_at;

        return (
          <section
            key={claim.claim_id}
            className="rounded border border-(--border) bg-(--surface-subtle) p-5"
            aria-label={`Claim review card ${claim.claim_id}`}
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-(--line) bg-(--line-2) px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-(--foreground)">
                    {claim.claim_id}
                  </span>
                  <span className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-primary">
                    {claim.domain.toUpperCase()}
                  </span>
                  <span
                    className={cx(
                      "rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em]",
                      dispositionTone(claim.current_disposition)
                    )}
                  >
                    {formatDispositionLabel(claim.current_disposition)}
                  </span>
                  {claim.confidence_band ? (
                    <span
                      className={cx(
                        "rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em]",
                        bandTone(claim.confidence_band)
                      )}
                    >
                      {formatBandLabel(claim.confidence_band)}
                    </span>
                  ) : null}
                  {typeof claim.confidence_score === "number" ? (
                    <span className="rounded-full border border-(--line) bg-(--line-2) px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-(--text-muted)">
                      Confidence {Math.round(claim.confidence_score * 100)}%
                    </span>
                  ) : null}
                </div>

                <div className="space-y-2">
                  <h3 className="text-lg font-semibold text-(--foreground)">{claim.claim_text}</h3>
                  {claim.critique_reference ? (
                    <p className="text-sm text-(--text-soft)">{claim.critique_reference}</p>
                  ) : null}
                </div>

                {evidenceLines.length > 0 ? (
                  <div className="rounded border border-(--line) bg-(--line-2) p-3">
                    <p className="text-[10px] font-black uppercase tracking-[0.18em] text-(--text-muted)">
                      Evidence Anchor
                    </p>
                    <ul className="mt-2 space-y-1 text-sm text-(--text-soft)">
                      {evidenceLines.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {claim.reason_codes.length > 0 ? (
                  <p className="text-xs text-(--text-muted)">
                    Signals: {claim.reason_codes.join(", ")}
                  </p>
                ) : null}

                {claim.review_decision ? (
                  <div className="rounded border border-(--line) bg-(--line-2) p-3 text-sm text-(--text-soft)">
                    <p className="font-medium text-(--foreground)">
                      {formatDispositionLabel(claim.current_disposition)}
                      {reviewedBy ? ` by ${reviewedBy}` : ""}
                    </p>
                    {reviewedAt ? (
                      <p className="mt-1 text-xs text-(--text-muted)">
                        <ClientSafeDate date={reviewedAt} format="datetime" />
                      </p>
                    ) : null}
                    {claim.review_decision.review_note ? (
                      <p className="mt-2">{claim.review_decision.review_note}</p>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <div className="w-full max-w-xl space-y-4 lg:min-w-[320px]">
                <TextAreaField
                  aria-label={`Review note for ${claim.claim_id}`}
                  label="Review note"
                  helperText="Optional justification. Limited to 500 characters."
                  rows={4}
                  maxLength={500}
                  value={notes[claim.claim_id] ?? ""}
                  onChange={(event) =>
                    setNotes((current) => ({
                      ...current,
                      [claim.claim_id]: event.target.value,
                    }))
                  }
                  disabled={!queue.can_review || isSubmitting}
                />
                <div className="flex flex-col gap-3 sm:flex-row">
                  <Button
                    type="button"
                    variant="primary"
                    className="sm:flex-1"
                    disabled={!queue.can_review}
                    loading={isSubmitting}
                    loadingText="Saving"
                    onClick={() => handleReview(claim, "manually_approved")}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Approve
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    className="sm:flex-1"
                    disabled={!queue.can_review}
                    loading={isSubmitting}
                    loadingText="Saving"
                    onClick={() => handleReview(claim, "manually_refused")}
                  >
                    <XCircle className="h-4 w-4" />
                    Refuse
                  </Button>
                </div>
                {!queue.can_review ? (
                  <p className="text-xs text-(--text-muted)">
                    Your role can inspect the review queue but cannot change claim dispositions.
                  </p>
                ) : null}
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
