"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import Modal from "@/components/ui/Modal";
import {
  VISIBILITY_PROVIDER_LABELS,
  offeredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";
import { createVisibilityQuery } from "@/services/monitoringService";
import type { VisibilityEntitlements, VisibilityProvider } from "@/types/monitoring";

export type SignalAddPromptModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Served by the visibility feed. Never a client-side copy of the plan ladder. */
  entitlements: VisibilityEntitlements | null;
  getAuthHeaders: () => Promise<HeadersInit>;
  onCreated: () => void | Promise<void>;
};

const QUERY_TYPES: Array<{ value: "aeo" | "geo"; labelKey: string }> = [
  { value: "aeo", labelKey: "signalAddPrompt.typeAeo" },
  { value: "geo", labelKey: "signalAddPrompt.typeGeo" },
];

const fieldLabelCls =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const inputCls =
  "h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-3 text-[13.5px] text-(--t-1) outline-hidden focus:border-[#C7CDD6]";

/**
 * Add prompt, on the surface the approved design puts it: the Prompts tab of
 * the AIO detail page (`Signal AIO Detail.html`, "Prompts we test"). Before
 * SIGV2-1142 the approved button navigated to a monitoring page the MVP does
 * not contain, and the form there refused silently once the plan cap was
 * reached. Here a refusal is stated with the cap, the used count, what remains
 * and the plan that raises it, all read from the entitlement the API serves.
 */
export default function SignalAddPromptModal({
  open,
  onClose,
  projectId,
  entitlements,
  getAuthHeaders,
  onCreated,
}: SignalAddPromptModalProps) {
  const { t } = useTranslation();
  const [promptText, setPromptText] = useState("");
  const [queryType, setQueryType] = useState<"aeo" | "geo">("aeo");
  // SIGV2-1197: no search-type choice. Jake ruled that a customer cannot be
  // expected to pick a scored type from a dropdown, so the type is assigned
  // by the backend from the wording and shown on the row once saved; a wrong
  // assignment is fixed by rewording, which the prompt-setup surface now
  // supports. The mockup's own live classifier is deliberately not replicated
  // here: a second classifier would drift from `suggest_search_type` on the
  // backend and the two would disagree.
  const [providers, setProviders] = useState<VisibilityProvider[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allowedProviders = useMemo(
    // SIGV2-1215: a withdrawn engine is never offered as a choice.
    () => offeredVisibilityProviders(entitlements?.allowed_providers),
    [entitlements?.allowed_providers]
  );

  // The engine selection follows the entitlement, so a plan change never
  // leaves a provider selected that the API would refuse.
  useEffect(() => {
    setProviders((current) => {
      const kept = current.filter((provider) => allowedProviders.includes(provider));
      if (kept.length > 0) return kept;
      return allowedProviders.length > 0 ? [allowedProviders[0]] : [];
    });
  }, [allowedProviders]);

  const planLabel = entitlements?.plan_label || entitlements?.plan || null;
  const maxPrompts =
    typeof entitlements?.max_queries === "number" ? entitlements.max_queries : null;
  const usedPrompts =
    typeof entitlements?.used_queries === "number" ? entitlements.used_queries : null;
  const remainingPrompts =
    typeof entitlements?.remaining_queries === "number"
      ? entitlements.remaining_queries
      : maxPrompts !== null && usedPrompts !== null
        ? Math.max(0, maxPrompts - usedPrompts)
        : null;

  const locked = entitlements?.is_locked === true;
  const capReached = !locked && remainingPrompts !== null && remainingPrompts <= 0;
  const upgradePlanLabel = entitlements?.upgrade_plan_label ?? null;
  const upgradeMax =
    typeof entitlements?.upgrade_max_queries === "number" ? entitlements.upgrade_max_queries : null;
  const upgradeHref = entitlements?.upgrade_plan
    ? `/dashboard/billing?section=plans&plan=${entitlements.upgrade_plan}`
    : "/dashboard/billing?section=plans";

  const refusal = locked
    ? planLabel
      ? t("signalAddPrompt.locked", { plan: planLabel })
      : t("signalAddPrompt.lockedUnknownPlan")
    : capReached
      ? t(planLabel ? "signalAddPrompt.capReached" : "signalAddPrompt.capReachedUnknownPlan", {
          plan: planLabel ?? "",
          max: maxPrompts ?? 0,
          used: usedPrompts ?? maxPrompts ?? 0,
          remaining: remainingPrompts ?? 0,
        })
      : null;

  const reset = () => {
    setPromptText("");
    setQueryType("aeo");
    setError(null);
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (refusal) {
      setError(refusal);
      return;
    }
    if (!promptText.trim()) {
      setError(t("signalAddPrompt.promptRequired"));
      return;
    }
    if (allowedProviders.length > 0 && providers.length === 0) {
      setError(t("signalAddPrompt.engineRequired"));
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      await createVisibilityQuery(
        projectId,
        {
          query_text: promptText.trim(),
          query_type: queryType,
          providers,
          // search_type stays absent: the backend assigns it from the wording.
        },
        headers
      );
      await onCreated();
      reset();
      onClose();
    } catch (err) {
      // The API states the cap, the usage and the plan that raises it, so its
      // own sentence is shown rather than a generic failure.
      setError(err instanceof Error && err.message ? err.message : t("signalAddPrompt.failed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      ariaLabelledby="signal-add-prompt-title"
      panelClassName="p-0! bg-transparent! border-0! shadow-none!"
    >
      <div
        data-signal-theme
        className="w-[560px] max-w-full rounded-[20px] border border-(--line) bg-(--panel) p-[28px_30px_26px] shadow-[0_40px_90px_-30px_rgba(12,15,22,0.5)]"
      >
        <p className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
          {t("signalAddPrompt.eyebrow")}
        </p>
        <h2
          id="signal-add-prompt-title"
          className="mt-2 font-(family-name:--disp) text-[23px] font-extrabold tracking-[-0.02em] text-(--t-1)"
        >
          {t("signalAddPrompt.title")}
        </h2>
        <p className="mb-4 mt-1.5 text-[13.5px] leading-normal text-(--t-2)">
          {t("signalAddPrompt.description")}
        </p>

        {/* Allowance, stated before anyone presses the button. */}
        <p className="mb-[18px] font-(family-name:--mono) text-[11px] text-(--t-3)" role="status">
          {maxPrompts !== null && usedPrompts !== null
            ? t(planLabel ? "signalAddPrompt.usage" : "signalAddPrompt.usageNoPlan", {
                used: usedPrompts,
                max: maxPrompts,
                remaining: remainingPrompts ?? 0,
                plan: planLabel ?? "",
              })
            : t("signalAddPrompt.usageUnknown")}
        </p>

        {refusal ? (
          <div
            role="alert"
            className="mb-[18px] rounded-[12px] border border-(--line) bg-(--paper) px-4 py-3 text-[12.5px] leading-[1.55] text-(--t-2)"
          >
            <p className="m-0 font-semibold text-(--t-1)">{refusal}</p>
            <p className="m-0 mt-1.5">
              {upgradePlanLabel && upgradeMax !== null
                ? t("signalAddPrompt.capUpgrade", { plan: upgradePlanLabel, max: upgradeMax })
                : t("signalAddPrompt.capRemove")}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link
                href={`/dashboard/projects/${projectId}/ai-answers?tab=prompts`}
                className="inline-flex h-8 items-center rounded-[10px] border border-(--line) bg-(--panel) px-[13px] text-[12.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
              >
                {t("signalAddPrompt.managePrompts")}
              </Link>
              {upgradePlanLabel ? (
                <Link
                  href={upgradeHref}
                  className="inline-flex h-8 items-center rounded-[10px] border border-(--ink) bg-(--ink) px-[13px] text-[12.5px] font-semibold text-white hover:bg-black"
                >
                  {t("signalAddPrompt.viewPlans")}
                </Link>
              ) : null}
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4">
          <label className="block">
            <span className={fieldLabelCls}>{t("signalAddPrompt.promptLabel")}</span>
            <input
              value={promptText}
              onChange={(event) => setPromptText(event.target.value)}
              placeholder={t("signalAddPrompt.promptPlaceholder")}
              maxLength={500}
              disabled={submitting}
              className={inputCls}
            />
          </label>

          <label className="block">
            <span className={fieldLabelCls}>{t("signalAddPrompt.typeLabel")}</span>
            <select
              value={queryType}
              onChange={(event) => setQueryType(event.target.value as "aeo" | "geo")}
              disabled={submitting}
              className={inputCls}
            >
              {QUERY_TYPES.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </option>
              ))}
            </select>
          </label>

          {/* SIGV2-1197: the type is stated, not asked. */}
          <p className="m-0 text-[11.5px] leading-[1.55] text-(--t-3)">
            {t("signalAddPrompt.searchTypeAssigned")}
          </p>

          {allowedProviders.length > 0 ? (
            <div>
              <span className={fieldLabelCls}>{t("signalAddPrompt.enginesLabel")}</span>
              <div className="flex flex-wrap gap-2">
                {allowedProviders.map((provider) => {
                  const checked = providers.includes(provider);
                  return (
                    <label
                      key={provider}
                      className={`inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-[12px] font-semibold transition-colors ${
                        checked
                          ? "border-(--ink) bg-(--ink) text-white"
                          : "border-(--line) bg-(--paper) text-(--t-2)"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        disabled={submitting}
                        onChange={() =>
                          setProviders((current) =>
                            current.includes(provider)
                              ? current.filter((item) => item !== provider)
                              : [...current, provider]
                          )
                        }
                      />
                      {VISIBILITY_PROVIDER_LABELS[provider] ?? provider}
                    </label>
                  );
                })}
              </div>
              <p className="mt-2 text-[11.5px] text-(--t-3)">{t("signalAddPrompt.enginesHint")}</p>
            </div>
          ) : null}
        </div>

        <p className="mt-4 text-[11.5px] leading-[1.5] text-(--t-3)">
          {t("signalAddPrompt.unmeasuredNote")}
        </p>

        {error ? (
          <p role="alert" className="mt-3 text-[12.5px] text-(--bad)">
            {error}
          </p>
        ) : null}

        <div className="mt-6 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="h-[38px] rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0] disabled:opacity-50"
          >
            {t("signalAddPrompt.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting || Boolean(refusal)}
            className="h-[38px] rounded-[10px] bg-(--ink) px-[15px] text-[13.5px] font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? t("signalAddPrompt.submitting") : t("signalAddPrompt.submit")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
