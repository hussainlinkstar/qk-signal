"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/custom-auth";
import GatedSection from "@/components/results/GatedSection";
import { CARD_SUBSECTION_SURFACE_CLASS } from "@/components/ui/cardStyleTokens";
import { cx } from "@/components/ui/utils";
import { formatDateTime } from "@/lib/dateFormat";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import { getErrorStatus, getPlanLockContent } from "@/lib/planLocks";
import {
  type BrandFact,
  type BrandFactKind,
  createBrandFact,
  deleteBrandFact,
  fetchBrandFacts,
} from "@/services/brandFactsService";

const KIND_OPTIONS: Array<{ value: BrandFactKind; label: string }> = [
  { value: "fact", label: "Fact" },
  { value: "claim", label: "Claim" },
];

const KIND_LABEL: Record<BrandFactKind, string> = {
  fact: "Fact",
  claim: "Claim",
};

const SAMPLE_PREVIEW_FACTS: ReadonlyArray<Pick<BrandFact, "kind" | "statement" | "is_forbidden">> =
  [
    { kind: "fact", statement: "Headquartered in Berlin since 2017.", is_forbidden: false },
    { kind: "claim", statement: "We do not claim to be the #1 provider.", is_forbidden: true },
  ];

type GuardrailsSectionProps = {
  projectId: string;
};

function GuardrailsPreview() {
  return (
    <div className={cx(CARD_SUBSECTION_SURFACE_CLASS, "space-y-3")}>
      {SAMPLE_PREVIEW_FACTS.map((fact, index) => (
        <div
          key={index}
          className="rounded border border-(--border) bg-(--surface-elevated) p-4 shadow-(--shadow-inset)"
        >
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-(--border) bg-(--surface-subtle) px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-(--text-muted)">
              {KIND_LABEL[fact.kind]}
            </span>
            {fact.is_forbidden ? (
              <span className="rounded-full border border-danger/25 bg-danger/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-danger">
                Forbidden
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-sm text-(--text-soft)">{fact.statement}</p>
        </div>
      ))}
    </div>
  );
}

export default function GuardrailsSection({ projectId }: GuardrailsSectionProps) {
  const { t } = useTranslation();
  const { getToken, isLoading: authLoading, isSignedIn, user } = useAuth();
  const capabilities = resolvePlanCapabilities(user?.subscription_plan);
  // Fail-safe locked: unknown / unresolved plans resolve every premium
  // capability to `false`, so the section stays gated until the plan is known
  // to include brand-integrity guardrails (Executive+).
  const planLocked = !capabilities.has_brand_integrity_guardrails;

  const [apiLocked, setApiLocked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [facts, setFacts] = useState<BrandFact[]>([]);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [kind, setKind] = useState<BrandFactKind>("fact");
  const [statement, setStatement] = useState("");
  const [isForbidden, setIsForbidden] = useState(false);

  const isLocked = planLocked || apiLocked;

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to manage brand guardrails.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadFacts = useCallback(async () => {
    if (!projectId || authLoading) {
      return;
    }
    if (!isSignedIn || planLocked) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const rows = await fetchBrandFacts(projectId, headers);
      setFacts(rows);
      setApiLocked(false);
    } catch (loadError) {
      if (getErrorStatus(loadError) === 402) {
        setApiLocked(true);
      } else {
        setError(
          loadError instanceof Error ? loadError.message : "Unable to load brand guardrails."
        );
      }
    } finally {
      setLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, planLocked, projectId]);

  useEffect(() => {
    void loadFacts();
  }, [loadFacts]);

  const handleAddFact = async () => {
    const trimmed = statement.trim();
    if (!trimmed) {
      setError("Enter a statement before adding a brand guardrail.");
      return;
    }

    setSaving(true);
    setFeedback(null);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const created = await createBrandFact(
        projectId,
        { kind, statement: trimmed, is_forbidden: isForbidden },
        headers
      );
      setFacts((current) => [created, ...current]);
      setStatement("");
      setIsForbidden(false);
      setKind("fact");
      setFeedback("Brand guardrail added.");
    } catch (createError) {
      if (getErrorStatus(createError) === 402) {
        setApiLocked(true);
      } else {
        setError(
          createError instanceof Error ? createError.message : "Unable to add brand guardrail."
        );
      }
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveFact = async (factId: number) => {
    setRemovingId(factId);
    setFeedback(null);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      await deleteBrandFact(projectId, factId, headers);
      setFacts((current) => current.filter((fact) => fact.id !== factId));
      setFeedback("Brand guardrail removed.");
    } catch (removeError) {
      if (getErrorStatus(removeError) === 402) {
        setApiLocked(true);
      } else {
        setError(
          removeError instanceof Error ? removeError.message : "Unable to remove brand guardrail."
        );
      }
    } finally {
      setRemovingId(null);
    }
  };

  if (isLocked) {
    const lock = getPlanLockContent("brandIntegrity");
    return (
      <GatedSection
        title="Brand Guardrails"
        teaser="Define the brand facts and forbidden claims the audit must respect so generated reports stay grounded in your truth."
        requiredPlan="plan_executive"
        requiredPlanLabel={lock.requiredPlanLabel}
        blurredPreview={<GuardrailsPreview />}
      />
    );
  }

  const shellCls = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";

  if (authLoading || loading) {
    return (
      <section className={shellCls}>
        <div className="flex items-center gap-3 text-[13px] text-(--t-3)">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading brand guardrails...
        </div>
      </section>
    );
  }

  if (!isSignedIn) {
    return (
      <section className={shellCls}>
        <p className="m-0 text-[13px] text-(--t-3)">
          Sign in to manage the brand facts and forbidden claims for this project.
        </p>
      </section>
    );
  }

  return (
    <section className={shellCls} data-testid="guardrails-section">
      {/* Approved `.wsec` head. */}
      <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
        Brand Integrity Guardrails
      </h3>
      <p className="mt-1 text-[12.5px] leading-[1.5] text-(--t-3)">
        Brand facts the audit must respect. Forbidden statements flag content the audit must never
        assert - passed to the audit as structured evidence to keep findings grounded.
      </p>

      <div className="mt-4 border-t border-t-(--line-2) pt-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <span
              className="mb-2 block font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
              id="brand-fact-kind-label"
            >
              Type
            </span>
            {/* Approved `.seg` group: Fact / Claim. */}
            <div
              className="inline-flex gap-[2px] rounded-[9px] border border-(--line) bg-(--paper) p-[3px] ltr:[direction:ltr]"
              role="group"
              aria-labelledby="brand-fact-kind-label"
            >
              {KIND_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={kind === option.value}
                  disabled={saving}
                  className={cx(
                    "cursor-pointer rounded-[6px] border-none px-3 py-1.5 font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-2) disabled:cursor-not-allowed disabled:opacity-50 max-md:min-h-11",
                    kind === option.value && "bg-(--ink) text-white"
                  )}
                  onClick={() => setKind(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="min-w-[220px] flex-1">
            <label
              className="mb-2 block font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
              htmlFor="brand-fact-statement"
            >
              Statement
            </label>
            <input
              id="brand-fact-statement"
              className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
              type="text"
              placeholder="e.g. Founded in 2019 in London"
              value={statement}
              disabled={saving}
              onChange={(event) => setStatement(event.target.value)}
            />
          </div>
          <button
            type="button"
            className="inline-flex h-[38px] flex-none cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-50 max-md:min-h-11"
            disabled={!statement.trim() || saving}
            onClick={() => void handleAddFact()}
          >
            <Plus className="h-4 w-4" />
            {saving ? "Adding..." : "Add Guardrail"}
          </button>
        </div>

        <div className="mt-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[13.5px] font-semibold">
              {t("signalAuditReport.guardrails.neverSay")}
            </div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              {t("signalAuditReport.guardrails.neverSayDesc")}
            </div>
          </div>
          <button
            type="button"
            role="switch"
            id="brand-fact-forbidden"
            aria-checked={isForbidden}
            aria-label={t("signalAuditReport.guardrails.neverSay")}
            disabled={saving}
            className="inline-flex flex-none cursor-pointer items-center justify-center border-none bg-transparent p-0 disabled:cursor-not-allowed disabled:opacity-50 max-md:min-h-11 max-md:min-w-11 ltr:[direction:ltr]"
            onClick={() => setIsForbidden((current) => !current)}
          >
            <span
              className={cx(
                "relative block h-6 w-[42px] rounded-full transition-colors",
                isForbidden ? "bg-(--good)" : "bg-(--line)"
              )}
            >
              <span
                className={cx(
                  "absolute top-[3px] block h-[18px] w-[18px] rounded-full bg-white transition-[left]",
                  isForbidden ? "left-[21px]" : "left-[3px]"
                )}
              />
            </span>
          </button>
        </div>

        {feedback ? (
          <p className="mt-3 text-[12px] text-(--good)" role="status">
            {feedback}
          </p>
        ) : null}
        {error ? (
          <p className="mt-3 text-[12px] text-(--bad)" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      <div className="mt-4 space-y-3">
        {facts.length === 0 ? (
          <div className="rounded-[10px] border border-dashed border-(--line) px-4 py-[26px] text-center text-[13px] text-(--t-3)">
            No guardrails yet.
          </div>
        ) : (
          facts.map((fact) => (
            <div
              key={fact.id}
              data-testid="guardrail-row"
              className="rounded-[12px] border border-(--line) bg-(--paper) px-[18px] py-4"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-(--line) bg-(--panel) px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-(--t-3)">
                      {KIND_LABEL[fact.kind]}
                    </span>
                    {fact.is_forbidden ? (
                      <span className="rounded-full border border-[color-mix(in_srgb,var(--bad)_40%,transparent)] bg-(--bad-s) px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-(--bad)">
                        Forbidden
                      </span>
                    ) : null}
                  </div>
                  <p className="m-0 text-[13.5px] text-(--t-1)">{fact.statement}</p>
                  {fact.created_at ? (
                    <p className="m-0 text-[12px] text-(--t-3)">
                      Added {formatDateTime(fact.created_at)}
                    </p>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="inline-flex h-8 flex-none cursor-pointer items-center gap-2 self-start rounded-[10px] border border-[color-mix(in_srgb,var(--bad)_40%,transparent)] bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--bad) disabled:cursor-not-allowed disabled:opacity-50 max-md:min-h-11"
                  disabled={removingId === fact.id}
                  onClick={() => void handleRemoveFact(fact.id)}
                  aria-label={`Remove guardrail: ${fact.statement}`}
                >
                  <Trash2 className="h-4 w-4" />
                  {removingId === fact.id ? "Removing..." : "Remove"}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
