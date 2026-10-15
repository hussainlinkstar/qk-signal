"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { BookOpen, Check, Copy, KeyRound, Loader2, Lock, RefreshCw, Trash2 } from "lucide-react";

import LockedFeatureButton from "@/components/dashboard/LockedFeatureButton";
import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import Button from "@/components/ui/Button";
import CyberField from "@/components/ui/CyberField";
import { GlassCard } from "@/components/ui/GlassComponents";
import { getPlanLockContent } from "@/lib/planLocks";
import { ClientSafeDate } from "@/lib/dateFormat";
import {
  createApiKey,
  fetchApiKeys,
  revokeApiKey,
  type ApiKeyListResponse,
} from "@/services/apiKeyService";
import { cx } from "@/components/ui/utils";

type ApiKeysSectionProps = {
  getAuthHeaders: () => Promise<HeadersInit>;
};

const resolveErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
};

const formatPlanLabel = (planType: string) =>
  planType
    .split("_")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1).toLowerCase())
    .join(" ");

export function ApiKeysSection({ getAuthHeaders }: ApiKeysSectionProps) {
  const [payload, setPayload] = useState<ApiKeyListResponse | null>(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  const loadKeys = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const response = await fetchApiKeys(headers);
      setPayload(response);
    } catch (err) {
      setError(resolveErrorMessage(err, "Failed to load API keys."));
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  const activeKeys = useMemo(
    () => (payload?.items ?? []).filter((item) => item.is_active),
    [payload]
  );
  const planLockContent = getPlanLockContent("apiAccess");

  const handleCreate = async () => {
    if (!name.trim()) {
      setError("API key name is required.");
      return;
    }

    setCreating(true);
    setError(null);
    setSuccess(null);
    setCopyState("idle");
    try {
      const headers = await getAuthHeaders();
      const response = await createApiKey({ name: name.trim() }, headers);
      setPayload((current) =>
        current
          ? {
              ...current,
              items: [response.item, ...current.items],
            }
          : null
      );
      setName("");
      setCreatedKey(response.api_key);
      setSuccess("API key created. Copy it now because it will not be shown again.");
    } catch (err) {
      setError(resolveErrorMessage(err, "Unable to create API key."));
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (apiKeyId: number) => {
    setBusyId(apiKeyId);
    setError(null);
    setSuccess(null);
    try {
      const headers = await getAuthHeaders();
      const response = await revokeApiKey(apiKeyId, headers);
      setPayload((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) => (item.id === apiKeyId ? response.item : item)),
            }
          : current
      );
      setSuccess("API key revoked.");
    } catch (err) {
      setError(resolveErrorMessage(err, "Unable to revoke API key."));
    } finally {
      setBusyId(null);
    }
  };

  const handleCopyKey = async () => {
    if (!createdKey) {
      return;
    }
    try {
      await navigator.clipboard.writeText(createdKey);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  return (
    <GlassCard className="relative overflow-hidden border-emerald-500/10  p-0">
      <div className="border-b border-(--line) p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded border border-emerald-500/20 bg-emerald-500/10 text-emerald-300 shadow-[0_0_20px_rgba(16,185,129,0.15)]">
              <KeyRound className="h-6 w-6" />
            </div>
            <div>
              <h3 className="text-xl font-bold text-(--t-1)">API Keys</h3>
              <p className="mt-1 text-xs font-black uppercase tracking-widest text-(--t-3)">
                Headless API Access
              </p>
              <p className="mt-4 max-w-3xl text-sm leading-7 text-(--t-2)">
                Provision workspace API keys for BI pipelines, polling integrations, and audit
                orchestration outside the dashboard. Keys are shown once at creation and can be
                revoked at any time.
              </p>
            </div>
          </div>

          <Link href={payload?.developer_hub_url ?? "/dashboard/developer"} className="shrink-0">
            <Button variant="ghost" className="h-10 px-4">
              <BookOpen className="h-4 w-4" />
              Developer Hub
            </Button>
          </Link>
        </div>
      </div>

      <div className="space-y-6 p-8">
        {loading ? (
          <div className="rounded border-0 bg-(--line-2) p-6 text-sm text-(--t-2)">
            Loading API keys...
          </div>
        ) : null}

        {!loading && payload && !payload.api_access_enabled ? (
          <PlanLockNotice {...planLockContent} badgeLabel="Plan Upgrade Required" className="p-6" />
        ) : null}

        {payload?.api_access_enabled ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
            <CyberField
              id="api-key-name"
              label="Key Name"
              placeholder="Looker Studio export"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Button
              onClick={handleCreate}
              loading={creating}
              disabled={!name.trim()}
              variant="outline"
              className="h-11 px-5"
            >
              <KeyRound className="h-4 w-4" />
              Create API Key
            </Button>
          </div>
        ) : !loading && payload ? (
          <LockedFeatureButton
            buttonLabel="Create API Key"
            helperText={`Current plan: ${formatPlanLabel(payload.plan_type)}. ${planLockContent.helperText ?? ""}`.trim()}
          />
        ) : null}

        <AnimatePresence initial={false}>
          {createdKey ? (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="rounded border border-emerald-400/20 bg-emerald-500/10 p-5"
            >
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="text-[10px] font-black uppercase tracking-[0.2em] text-emerald-200">
                    Copy This Key Now
                  </p>
                  <div className="mt-3 rounded-xl border-0 bg-black/30 p-4 font-mono text-sm text-emerald-50 break-all">
                    {createdKey}
                  </div>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button onClick={handleCopyKey} variant="inverse" className="h-10 px-4">
                    {copyState === "copied" ? (
                      <Check className="h-4 w-4" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                    {copyState === "copied"
                      ? "Copied"
                      : copyState === "failed"
                        ? "Copy Failed"
                        : "Copy Key"}
                  </Button>
                  <Button
                    onClick={() => {
                      setCreatedKey(null);
                      setCopyState("idle");
                    }}
                    variant="ghost"
                    className="h-10 px-4"
                  >
                    Dismiss
                  </Button>
                </div>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <div className="overflow-hidden rounded border-0">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-(--line-2) text-[10px] font-black uppercase tracking-[0.18em] text-(--t-3)">
                <th className="px-6 py-4">Key</th>
                <th className="px-6 py-4">Scopes</th>
                <th className="px-6 py-4">Last Used</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y ">
              {!loading && (payload?.items.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-10 text-center text-sm text-(--t-3)">
                    No API keys issued yet.
                  </td>
                </tr>
              ) : null}

              {(payload?.items ?? []).map((item) => (
                <tr key={item.id} className="group transition-colors hover:bg-(--line-2)">
                  <td className="px-6 py-5">
                    <div className="space-y-1">
                      <p className="text-sm font-semibold text-(--t-1)">{item.name}</p>
                      <p className="font-mono text-xs text-(--t-2)">
                        {item.key_prefix}
                        ****
                        {item.key_last_four ?? "----"}
                      </p>
                      <div className="flex flex-wrap gap-2 pt-1">
                        <span
                          className={cx(
                            "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em]",
                            item.is_active
                              ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                              : "border-rose-400/20 bg-rose-500/10 text-rose-200"
                          )}
                        >
                          {item.is_active ? "Active" : "Revoked"}
                        </span>
                        <span className="inline-flex items-center rounded-full border-0 bg-(--line-2) px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-(--t-2)">
                          Created{" "}
                          <span className="ml-1">
                            {item.created_at ? (
                              <ClientSafeDate date={item.created_at} format="date" />
                            ) : (
                              "recently"
                            )}
                          </span>
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-5">
                    <div className="flex flex-wrap gap-2">
                      {item.scopes.map((scope) => (
                        <span
                          key={scope}
                          className="inline-flex items-center rounded-full border-0 bg-(--line-2) px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.16em] text-(--t-2)"
                        >
                          {scope}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-6 py-5 text-sm text-(--t-2)">
                    {item.last_used_at ? (
                      <ClientSafeDate date={item.last_used_at} format="datetime" />
                    ) : (
                      "Never used"
                    )}
                  </td>
                  <td className="px-6 py-5 text-right">
                    {item.is_active ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void handleRevoke(item.id)}
                        disabled={busyId === item.id}
                        className="h-9 rounded-xl px-3 text-rose-300 hover:bg-rose-500/10"
                        aria-label={`Revoke ${item.name}`}
                      >
                        {busyId === item.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                        Revoke
                      </Button>
                    ) : (
                      <span className="inline-flex items-center gap-2 text-xs text-(--t-3)">
                        <Lock className="h-3.5 w-3.5" />
                        Disabled
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col gap-3 rounded border-0 bg-(--line-2) p-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-(--t-3)">
              Quick Summary
            </p>
            <p className="mt-2 text-sm text-(--t-2)">
              {activeKeys.length} active key{activeKeys.length === 1 ? "" : "s"} ready for external
              audit orchestration.
            </p>
          </div>
          <Button onClick={() => void loadKeys()} variant="ghost" className="h-10 px-4">
            <RefreshCw className="h-4 w-4" />
            Refresh Keys
          </Button>
        </div>

        {error ? (
          <SignalAlert tone="danger" title="API key request failed">
            {error}
          </SignalAlert>
        ) : null}
        {success ? (
          <SignalAlert tone="success" title="API key updated">
            {success}
          </SignalAlert>
        ) : null}
      </div>
    </GlassCard>
  );
}

export default ApiKeysSection;
