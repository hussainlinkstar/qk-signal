"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, ShieldCheck, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import Button from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";
import { getPlanLockContent } from "@/lib/planLocks";
import type {
  CommitmentActionResponse,
  CommitmentSurfaceResponse,
  CommitmentTierId,
} from "@/types/billing";

type CommitmentTierSelectorProps = {
  getAuthHeaders: () => Promise<Record<string, string>>;
};

const formatMoney = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

// SIGNAL-1002: this showed the raw slug ("plan executive") instead of the
// plan's real name. `CommitmentSurfaceResponse.current_plan` only carries the
// slug, so map it the same way the admin subscriptions page does.
const formatPlanLabel = (plan: string | null): string => {
  if (!plan) return "Starter";
  const normalized = plan.trim().toLowerCase();
  if (normalized === "plan_starter") return "Starter";
  if (normalized === "plan_standard") return "Standard";
  if (normalized === "plan_specialist") return "Specialist";
  if (normalized === "plan_executive") return "Executive";
  return plan.replace(/^plan_/, "").replace(/_/g, " ");
};

const formatDate = (value: string | null) => {
  if (!value) {
    return "N/A";
  }
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(new Date(value));
  } catch {
    return value;
  }
};

export default function CommitmentTierSelector({ getAuthHeaders }: CommitmentTierSelectorProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<CommitmentSurfaceResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState("");
  const scheduledAuditsLock = getPlanLockContent("scheduledAudits");

  const loadSurface = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/billing/commitment-tiers", { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? t("signalCommitments.errors.load"));
      }
      setData((await response.json()) as CommitmentSurfaceResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("signalCommitments.errors.load"));
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, t]);

  useEffect(() => {
    void loadSurface();
  }, [loadSurface]);

  const activeCommitment = data?.commitment ?? null;

  const handleCheckout = useCallback(
    async (tier: CommitmentTierId) => {
      setActionMessage("");
      setActionLoading(`checkout:${tier}`);
      try {
        const headers = await getAuthHeaders();
        const response = await fetch("/api/billing/commitment-checkout", {
          method: "POST",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ tier }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? t("signalCommitments.errors.checkout"));
        }
        const payload = (await response.json()) as { checkout_url?: string };
        if (!payload.checkout_url) {
          throw new Error(t("signalCommitments.errors.checkoutUrlMissing"));
        }
        window.location.assign(payload.checkout_url);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("signalCommitments.errors.checkout"));
        setActionLoading(null);
      }
    },
    [getAuthHeaders, t]
  );

  const handleCancel = useCallback(async () => {
    if (!window.confirm(t("signalCommitments.cancelConfirm"))) {
      return;
    }
    setActionMessage("");
    setActionLoading("cancel");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/billing/commitment-cancel", {
        method: "POST",
        headers,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? t("signalCommitments.errors.cancel"));
      }
      const payload = (await response.json()) as CommitmentActionResponse;
      setActionMessage(payload.message ?? t("signalCommitments.cancelScheduled"));
      await loadSurface();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("signalCommitments.errors.cancel"));
    } finally {
      setActionLoading(null);
    }
  }, [getAuthHeaders, loadSurface, t]);

  const handleChangeTier = useCallback(
    async (tier: CommitmentTierId) => {
      setActionMessage("");
      setActionLoading(`change:${tier}`);
      try {
        const headers = await getAuthHeaders();
        const response = await fetch("/api/billing/commitment-change", {
          method: "POST",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ tier }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? t("signalCommitments.errors.changeTier"));
        }
        const payload = (await response.json()) as CommitmentActionResponse;
        setActionMessage(payload.message ?? t("signalCommitments.tierChangeScheduled"));
        await loadSurface();
      } catch (err) {
        setError(err instanceof Error ? err.message : t("signalCommitments.errors.changeTier"));
      } finally {
        setActionLoading(null);
      }
    },
    [getAuthHeaders, loadSurface, t]
  );

  // SIGV2-1128: the cycle state is read from flags, never from a credit
  // quantity. `in_overage` and `nearing_limit` are computed server-side so the
  // customer surface can describe the cycle without publishing the internal
  // credit figures behind it.
  const usageTone = useMemo(() => {
    if (!activeCommitment) {
      return "normal";
    }
    if (activeCommitment.in_overage) {
      return "overage";
    }
    if (activeCommitment.nearing_limit) {
      return "warning";
    }
    return "normal";
  }, [activeCommitment]);

  if (isLoading) {
    return (
      <div className="rounded-[12px] border-0 bg-[#EEF1F6] bg-(--line-2) p-8 text-(--t-2)">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 animate-spin text-(--t-2)" />
          <span className="text-sm">{t("signalCommitments.loading")}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-[12px] border-0 bg-[#EEF1F6] bg-(--line-2) text-(--t-2)">
              <TrendingUp className="h-5 w-5" />
            </div>
            <h2 className="text-xl font-semibold text-(--t-1)">{t("signalCommitments.title")}</h2>
          </div>
          <p className="max-w-2xl text-sm text-(--t-2)">{t("signalCommitments.intro")}</p>
        </div>
        {data?.current_plan ? (
          <div className="rounded-[12px] border-0 bg-[#EEF1F6] bg-(--line-2) px-4 py-3 text-xs text-(--t-3)">
            {t("signalCommitments.currentPlan")}{" "}
            <span className="text-(--t-2)">{formatPlanLabel(data.current_plan)}</span>
          </div>
        ) : null}
      </div>

      {error ? (
        <SignalAlert tone="danger" title="Commitment request failed">
          {error}
        </SignalAlert>
      ) : null}
      {actionMessage ? (
        <SignalAlert tone="success" title="Commitment updated">
          {actionMessage}
        </SignalAlert>
      ) : null}

      {!data?.eligible ? (
        <div className="rounded-[12px] border-0 bg-[#EEF1F6] bg-(--line-2) p-5">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 text-(--t-2)" />
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-(--t-2)">
                {t("signalCommitments.lockedTitle", {
                  plan: scheduledAuditsLock.requiredPlanLabel,
                })}
              </p>
              <p className="mt-2 text-sm leading-relaxed text-(--t-2)">
                {data?.locked_reason ??
                  t("signalCommitments.lockedBody", {
                    plan: scheduledAuditsLock.requiredPlanLabel,
                  })}
              </p>
            </div>
          </div>
        </div>
      ) : null}

      {activeCommitment ? (
        <div className="rounded-[12px] border-0 bg-[#EEF1F6] bg-(--line-2) p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-(--t-3)">
                {t("signalCommitments.activeLabel")}
              </p>
              <h3 className="mt-2 text-2xl font-semibold text-(--t-1)">
                {activeCommitment.tier.replace(/_/g, " ")}
              </h3>
              {/* SIGV2-1128: this sentence used to read "<used> / <committed>
                used this cycle", which published two internal credit figures on
                the page a customer reads as a bill. The cycle is stated by its
                dates; the committed volume lives in the agreement, and the
                backend has no scan-denominated equivalent to put here. */}
              <p className="mt-2 text-sm text-(--t-2)">
                {t("signalCommitments.cycleEnds", {
                  date: formatDate(activeCommitment.cycle_end),
                })}
              </p>
              {activeCommitment.pending_tier ? (
                <p className="mt-2 text-sm text-(--t-2)">
                  {t("signalCommitments.pendingChange", {
                    tier: activeCommitment.pending_tier.replace(/_/g, " "),
                    date: formatDate(activeCommitment.pending_change_effective_at),
                  })}
                </p>
              ) : null}
            </div>
            <div className="grid gap-2 text-sm text-(--t-2)">
              <div className="rounded-[12px] border-0 bg-[#EEF1F6] bg-(--line-2) px-4 py-3">
                <div className="text-xs uppercase tracking-wide text-(--t-3)">
                  {t("signalCommitments.monthlyFee")}
                </div>
                <div className="mt-2 text-lg font-semibold text-(--t-1)">
                  {formatMoney(activeCommitment.monthly_fee_usd)}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3 text-sm">
            <span
              className={cx(
                "rounded-full px-3 py-1 text-xs uppercase tracking-wide",
                usageTone === "overage"
                  ? "bg-red-500/10 text-red-400"
                  : usageTone === "warning"
                    ? "bg-amber-500/10 text-amber-400"
                    : "bg-emerald-500/10 text-emerald-400"
              )}
            >
              {usageTone === "overage"
                ? t("signalCommitments.statusOverCommitment")
                : usageTone === "warning"
                  ? t("signalCommitments.statusNearingCommitment")
                  : t("signalCommitments.statusOnTrack")}
            </span>
            <span className="text-(--t-2)">
              {usageTone === "overage"
                ? t("signalCommitments.statusOverCommitmentDetail")
                : usageTone === "warning"
                  ? t("signalCommitments.statusNearingCommitmentDetail")
                  : t("signalCommitments.statusOnTrackDetail")}
            </span>
            {activeCommitment.cancel_at_period_end ? (
              <span className="text-amber-400">{t("signalCommitments.cancellationScheduled")}</span>
            ) : null}
          </div>

          {!activeCommitment.cancel_at_period_end ? (
            <div className="mt-5 flex flex-wrap gap-3">
              {(data?.tiers ?? [])
                .filter((tier) => tier.tier !== activeCommitment.tier)
                .map((tier) => (
                  <Button
                    key={tier.tier}
                    variant="ghost"
                    loading={actionLoading === `change:${tier.tier}`}
                    onClick={() => void handleChangeTier(tier.tier)}
                  >
                    {t("signalCommitments.changeTo", { tier: tier.label })}
                  </Button>
                ))}
              <Button
                variant="danger"
                loading={actionLoading === "cancel"}
                onClick={() => void handleCancel()}
              >
                {t("signalCommitments.cancelAtPeriodEnd")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-(--line) bg-(--line-2) p-5">
          <div className="flex items-start gap-3">
            <TrendingUp className="mt-0.5 h-5 w-5 text-(--t-2)" />
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-(--t-2)">
                {t("signalCommitments.noneTitle")}
              </p>
              <p className="mt-2 text-sm text-(--t-2)">{t("signalCommitments.noneBody")}</p>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {(data?.tiers ?? []).map((tier) => {
          const isCurrent = activeCommitment?.tier === tier.tier;
          const isPending = activeCommitment?.pending_tier === tier.tier;
          return (
            <div
              key={tier.tier}
              className={cx(
                "rounded-md border p-5 transition-colors",
                isCurrent ? "border-primary/30 bg-(--line-2)" : "border-(--line) bg-(--line-2)"
              )}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-(--t-3)">
                    {tier.label}
                  </p>
                  <h3 className="mt-2 text-2xl font-semibold text-(--t-1)">
                    {formatMoney(tier.monthly_fee_usd)}
                  </h3>
                </div>
                <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs uppercase tracking-wide text-emerald-400">
                  {t("signalCommitments.discountOff", { percent: tier.discount_pct })}
                </span>
              </div>

              {/* SIGV2-1128: the three lines here stated the committed volume
                and the two rates in credits. Only the fee and the discount are
                expressible in the customer's units today. */}
              <div className="mt-4 space-y-2 text-sm text-(--t-2)">
                <div>{t("signalCommitments.tierFee")}</div>
                <div>{t("signalCommitments.tierDiscount", { percent: tier.discount_pct })}</div>
              </div>

              <div className="mt-5">
                {isCurrent ? (
                  <div className="rounded-md bg-(--line-2) px-4 py-2.5 text-center text-xs uppercase tracking-wide text-(--t-3)">
                    {t("signalCommitments.currentTier")}
                  </div>
                ) : isPending ? (
                  <div className="rounded-md bg-(--line-2) px-4 py-2.5 text-center text-xs uppercase tracking-wide text-(--t-3)">
                    {t("signalCommitments.scheduledNextCycle")}
                  </div>
                ) : (
                  <Button
                    variant="ghost"
                    className="w-full"
                    disabled={!data?.eligible || actionLoading !== null}
                    loading={actionLoading === `checkout:${tier.tier}`}
                    onClick={() => void handleCheckout(tier.tier)}
                  >
                    {t("signalCommitments.startTier", { tier: tier.label })}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-(--t-3)">{t("signalCommitments.volumeNote")}</p>
    </div>
  );
}
