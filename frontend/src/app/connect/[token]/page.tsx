"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import { asset } from "@/lib/basePath";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  Database,
  Eye,
  Fingerprint,
  ShieldAlert,
  Lock,
  ShieldCheck,
  Timer,
} from "lucide-react";

import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import BrandMark from "@/components/ui/BrandMark";
import { cx } from "@/components/ui/utils";

type MagicLinkStatusPayload = {
  valid: boolean;
  token: string;
  project_id: number | null;
  workspace_id: number | null;
  project_name: string | null;
  domain_url: string | null;
  expires_at: string | null;
  is_used: boolean;
  connection_state: "invalid" | "pending" | "expired" | "used" | "connected";
  providers: Array<{
    provider: "google" | "bing";
    connected: boolean;
    connected_at: string | null;
  }>;
};

const asMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
};

const TRUST_SIGNALS = [
  {
    icon: Lock,
    label: "End-to-end encryption",
    detail: "OAuth 2.0 with PKCE flow. Credentials never touch our servers.",
  },
  {
    icon: Eye,
    label: "Read-only access",
    detail: "We request the minimum scopes needed, analytics and search data only.",
  },
  {
    icon: Database,
    label: "Zero data retention",
    detail: "Raw provider data is processed in-memory and never stored long-term.",
  },
  {
    icon: Fingerprint,
    label: "Revoke anytime",
    detail: "Disconnect instantly from your Google or Microsoft account settings.",
  },
];

const PROVIDER_META: Record<
  "google" | "bing",
  { label: string; sublabel: string; description: string }
> = {
  google: {
    label: "Google",
    sublabel: "Search Console & GA4",
    description:
      "Grant read-only access to Search Console performance data and Google Analytics 4 properties.",
  },
  bing: {
    label: "Microsoft",
    sublabel: "Bing Webmaster Tools",
    description:
      "Grant read-only access to Bing search performance, crawl data, and indexing signals.",
  },
};

export default function MagicLinkConnectPage() {
  const params = useParams<{ token: string }>();
  const searchParams = useSearchParams();
  const token = useMemo(() => params?.token ?? "", [params?.token]);
  const [status, setStatus] = useState<MagicLinkStatusPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [connectingProvider, setConnectingProvider] = useState<"google" | "bing" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [messageType, setMessageType] = useState<"success" | "error" | "info">("info");

  const loadStatus = useCallback(async () => {
    if (!token) {
      setLoading(false);
      setStatus(null);
      setMessage("Magic link token is missing.");
      setMessageType("error");
      return;
    }

    setLoading(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/magic-links/${encodeURIComponent(token)}`, {
        method: "GET",
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail || "Unable to validate magic link.");
      }
      const payload = (await response.json()) as MagicLinkStatusPayload;
      setStatus(payload);
    } catch (error) {
      setStatus(null);
      setMessage(asMessage(error, "Unable to validate magic link."));
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    const callbackProvider = searchParams.get("provider");
    const callbackStatus = searchParams.get("status");
    const callbackMessage = searchParams.get("message");
    if (!callbackProvider || !callbackStatus) {
      return;
    }

    if (callbackStatus === "connected") {
      setMessage(
        `${callbackProvider.charAt(0).toUpperCase() + callbackProvider.slice(1)} connected successfully. Your agency can now access mapped project data sources.`
      );
      setMessageType("success");
      void loadStatus();
      return;
    }

    if (callbackStatus === "error") {
      setMessage(
        callbackMessage
          ? `Connection failed (${callbackProvider}): ${callbackMessage}`
          : `Connection failed for ${callbackProvider}.`
      );
      setMessageType("error");
    }
  }, [loadStatus, searchParams]);

  const startProviderOAuth = (provider: "google" | "bing") => {
    if (!token) {
      setMessage("Magic link token is missing.");
      setMessageType("error");
      return;
    }
    setConnectingProvider(provider);
    setMessage(null);
    window.location.href = asset(
      `/api/magic-links/${encodeURIComponent(token)}/oauth/${provider}/start`
    );
  };

  const allConnected = status?.providers.every((p) => p.connected) ?? false;
  const anyConnected = status?.providers.some((p) => p.connected) ?? false;

  // signal-light standalone page: the mockup has no handshake screen, so this
  // follows the approved standalone-card vocabulary used by the auth shell -
  // `signal-canvas` background, `--panel` card with `--r` radius and `--line`
  // hairlines, `.conn` rows for the providers and `.badge-ok`/`.tag` chips
  // for state.
  return (
    <main className="signal-canvas min-h-dvh px-4 py-8 font-(family-name:--body-font) text-(--t-1) antialiased sm:py-12">
      <div className="mx-auto w-full max-w-[520px]">
        <Link
          href="/login"
          aria-label="Return to sign in"
          className="mb-6 flex w-fit items-center rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--brand)"
        >
          <SignalBrandLockup />
        </Link>

        <div className="rounded-[22px] border-0 bg-white p-6">
          <span className="inline-flex items-center gap-1.5 rounded-[6px] bg-(--purple-a10) px-[7px] py-[3px] font-mono text-[9.5px] uppercase tracking-[0.06em] text-(--purple-deep)">
            <ShieldCheck size={12} strokeWidth={2} aria-hidden="true" />
            Secure data handshake
          </span>
          <h1 className="m-0 mt-3 font-(family-name:--disp) text-[22px] font-extrabold leading-[1.25] tracking-[-0.02em] text-(--t-1)">
            Connect your data sources
          </h1>
          <p className="mt-2 text-[13px] leading-[1.5] text-(--t-2)">
            Authorize read-only access so your agency can map analytics into the project workspace.
            You can revoke access at any time.
          </p>

          {message ? (
            <div
              role={messageType === "error" ? "alert" : "status"}
              className={cx(
                "mt-4 flex items-start gap-2.5 rounded-[10px] border px-3.5 py-3 text-[12.5px] leading-[1.5]",
                messageType === "success"
                  ? "border-(--good) bg-(--good-s) text-(--good)"
                  : messageType === "error"
                    ? "border-(--bad) bg-[color-mix(in_srgb,var(--bad)_8%,var(--panel))] text-(--bad)"
                    : "border-(--line) bg-(--paper) text-(--t-2)"
              )}
            >
              {messageType === "success" ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              ) : messageType === "error" ? (
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              ) : null}
              <span>{message}</span>
            </div>
          ) : null}

          {loading ? (
            <div className="mt-6 flex flex-col gap-3" role="status" aria-label="Validating link">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-[52px] animate-pulse rounded-[14px] border-0 bg-[#EEF1F6]"
                />
              ))}
              <span className="sr-only">Validating link...</span>
            </div>
          ) : null}

          {!loading && status ? (
            <div className="mt-5">
              {/* Project block: what this link grants access to */}
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="m-0 font-mono text-[9.5px] uppercase tracking-[0.06em] text-(--t-3)">
                    Project
                  </p>
                  <p className="m-0 mt-1 truncate font-(family-name:--disp) text-[17px] font-bold tracking-[-0.01em]">
                    {status.project_name || "Unknown project"}
                  </p>
                  <p className="m-0 mt-0.5 truncate text-[12.5px] text-(--t-3)">
                    {status.domain_url || "Domain not configured"}
                  </p>
                </div>
                <span
                  className={cx(
                    "flex flex-none items-center gap-1 rounded-[6px] px-[7px] py-[3px] font-mono text-[9.5px] uppercase tracking-[0.06em]",
                    status.valid
                      ? "bg-(--good-s) text-(--good)"
                      : "bg-[color-mix(in_srgb,var(--warn)_12%,var(--panel))] text-(--warn)"
                  )}
                >
                  {status.valid ? (
                    <>
                      <ShieldCheck className="h-3 w-3" aria-hidden="true" />
                      Valid
                    </>
                  ) : (
                    <>
                      <ShieldAlert className="h-3 w-3" aria-hidden="true" />
                      {status.connection_state === "expired"
                        ? "Expired"
                        : status.connection_state === "used"
                          ? "Used"
                          : "Invalid"}
                    </>
                  )}
                </span>
              </div>

              {status.expires_at ? (
                <p className="m-0 mt-2 flex items-center gap-1.5 font-mono text-[10.5px] text-(--t-3)">
                  <Timer className="h-3 w-3" aria-hidden="true" />
                  Expires{" "}
                  {new Date(status.expires_at).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              ) : null}

              {/* Provider rows: approved `.conn` anatomy - 32px icon tile,
                  13.5/600 title, mono descriptor, action or badge-ok. */}
              {status.valid ? (
                <div className="mt-4">
                  {status.providers.map((provider) => {
                    const meta = PROVIDER_META[provider.provider];
                    return (
                      <div
                        key={provider.provider}
                        className="flex items-center gap-3 border-t border-t-(--line-2) py-3 first:border-t-0"
                      >
                        <span className="flex h-8 w-8 flex-none items-center justify-center rounded-[8px] bg-(--line-2)">
                          <BrandMark
                            brand={provider.provider === "bing" ? "bing" : "google"}
                            markClassName="h-[17px] w-[17px]"
                          />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="text-[13.5px] font-semibold">{meta.label}</div>
                          <div className="font-mono text-[11.5px] text-(--t-3)">
                            {meta.sublabel}
                          </div>
                          <p className="m-0 mt-1 text-[12px] leading-[1.45] text-(--t-3)">
                            {meta.description}
                          </p>
                          {provider.connected && provider.connected_at ? (
                            <p className="m-0 mt-1 font-mono text-[10.5px] text-(--good)">
                              Connected{" "}
                              {new Date(provider.connected_at).toLocaleDateString(undefined, {
                                month: "short",
                                day: "numeric",
                                year: "numeric",
                              })}
                            </p>
                          ) : null}
                        </div>
                        {provider.connected ? (
                          <span className="flex flex-none items-center gap-1 rounded-[999px] bg-(--good-s) px-[9px] py-1 font-mono text-[10.5px] text-(--good)">
                            <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                            Connected
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => startProviderOAuth(provider.provider)}
                            disabled={connectingProvider !== null}
                            className="inline-flex h-8 flex-none cursor-pointer items-center gap-1.5 rounded-full border-0 bg-[#111827] px-[15px] text-[13.5px] font-semibold text-(--panel) hover:brightness-95 disabled:opacity-60 max-md:min-h-11"
                          >
                            {connectingProvider === provider.provider
                              ? "Redirecting..."
                              : "Authorize"}
                            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <SignalAlert tone="warning" title="Link unavailable" className="mt-4">
                  This link has expired, was already used, or is invalid. Contact your agency to
                  request a new secure handshake link.
                </SignalAlert>
              )}

              {allConnected && status.valid ? (
                <SignalAlert tone="success" title="All providers connected" className="mt-4">
                  Your agency now has read-only access to the mapped data sources. You can close
                  this page.
                </SignalAlert>
              ) : null}

              <div className="mt-5 flex items-center justify-between border-t border-(--line-2) pt-4">
                <Link
                  href="/login"
                  className="inline-flex min-h-11 items-center rounded-sm text-[13px] font-medium text-(--t-2) transition-colors hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand)"
                >
                  Back to Qiko Signal
                </Link>
                {anyConnected && !allConnected ? (
                  <p className="m-0 font-mono text-[10.5px] text-(--t-3)">
                    {status?.providers.filter((p) => p.connected).length} of{" "}
                    {status?.providers.length} connected
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        {!loading && status?.valid ? (
          <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {TRUST_SIGNALS.map((signal) => {
              const Icon = signal.icon;
              return (
                <div
                  key={signal.label}
                  className="flex items-start gap-2.5 rounded-full border-0 bg-[#EEF1F6] p-3"
                >
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-(--t-3)" aria-hidden="true" />
                  <div>
                    <p className="m-0 text-[11.5px] font-semibold text-(--t-1)">{signal.label}</p>
                    <p className="m-0 mt-0.5 text-[11px] leading-[1.45] text-(--t-3)">
                      {signal.detail}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}

        <p className="mt-6 text-center text-[11.5px] text-(--t-3)">
          &copy; {new Date().getFullYear()} Qiko Signal. All rights reserved.
        </p>
      </div>
    </main>
  );
}
