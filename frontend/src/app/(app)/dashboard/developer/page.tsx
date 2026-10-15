"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import Link from "next/link";
import React, { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";

import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import WorkspacePageFrame from "@/components/dashboard/WorkspacePageFrame";
import SignalTabs, { SignalTabPanel } from "@/components/signal/SignalTabs";
import { useAuth } from "@/components/auth/custom-auth";
import { cx } from "@/components/ui/utils";
import { getPlanLockContent } from "@/lib/planLocks";
import { PLAN_DISPLAY_NAMES } from "@/lib/planCapabilities";
import {
  fetchApiKeys,
  type ApiKeyListResponse,
  type CanonicalSubscriptionPlan,
} from "@/services/apiKeyService";
import {
  codeSamples,
  endpointRows,
  mcpClaudeDesktopConfig,
  mcpEndpointUrl,
  mcpSamples,
  mcpToolRows,
} from "./content";
import RawJsonReportCard from "./RawJsonReportCard";

const quickStartSteps = [
  {
    id: "keys",
    n: "1",
    title: "Create a workspace key",
    description:
      "Generate a dedicated key in Workspace Settings. Raw secrets are visible only once at creation time.",
    href: "/dashboard/settings",
    action: "Manage API Keys",
  },
  {
    id: "request",
    n: "2",
    title: "Submit an audit job",
    description:
      "POST to the external API with url, tier, and an idempotency_key for safe retries.",
    href: "/dashboard/developer/docs",
    action: "Review Docs",
  },
  {
    id: "delivery",
    n: "3",
    title: "Poll or webhook delivery",
    description:
      "Poll the job endpoint for status changes or pass webhook_url to receive the signed payload.",
    href: "/dashboard/developer/docs",
    action: "View Delivery Docs",
  },
] as const;

const canonicalPlanDisplayNames = PLAN_DISPLAY_NAMES;

const rateLimitByPlan = {
  plan_specialist: { summary: "60 req/min", detail: "1,000 requests per day" },
  plan_executive: { summary: "300 req/min", detail: "10,000 requests per day" },
} as const;

function isCanonicalSubscriptionPlan(value: string): value is CanonicalSubscriptionPlan {
  return Object.prototype.hasOwnProperty.call(canonicalPlanDisplayNames, value);
}

function formatPlanType(planType: string | null | undefined) {
  if (!planType || !isCanonicalSubscriptionPlan(planType)) {
    return "Plan unavailable";
  }
  return canonicalPlanDisplayNames[planType];
}

function resolveRateLimit(
  planType: string | null | undefined,
  apiAccessEnabled: boolean | undefined
) {
  if (!apiAccessEnabled) {
    return { summary: "Locked", detail: "Upgrade in Billing to enable the external API" };
  }
  return (
    rateLimitByPlan[planType as keyof typeof rateLimitByPlan] ?? {
      summary: "Plan-specific",
      detail: "Provisioned according to your active subscription",
    }
  );
}

type DevTab = "hub" | "quickstart" | "reference" | "mcp";

const DEV_TABS: { id: DevTab; label: string }[] = [
  { id: "hub", label: "Hub" },
  { id: "quickstart", label: "Quick Start" },
  { id: "reference", label: "API Reference" },
  { id: "mcp", label: "MCP Setup" },
];

export default function DeveloperHubPage() {
  const { getToken, isLoading: authLoading, isSignedIn } = useAuth();
  const [payload, setPayload] = useState<ApiKeyListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<DevTab>("hub");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      if (authLoading || !isSignedIn) {
        if (!authLoading) setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const token = await getToken();
        if (!token) {
          setLoading(false);
          return;
        }
        setPayload(await fetchApiKeys({ Authorization: `Bearer ${token}` }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load developer access details.");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [authLoading, getToken, isSignedIn]);

  const planLockContent = getPlanLockContent("apiAccess");
  const mcpLockContent = getPlanLockContent("mcpAccess");
  const activeKeyCount = (payload?.items ?? []).filter((item) => item.is_active).length;
  const apiEnabled = Boolean(payload?.api_access_enabled);
  const mcpEnabled = Boolean(payload?.mcp_access_enabled);
  const accessLabel = loading ? "Checking" : apiEnabled ? "Enabled" : "Locked";
  const planName = error ? "Status unavailable" : formatPlanType(payload?.plan_type);
  const throughput = resolveRateLimit(payload?.plan_type, payload?.api_access_enabled);
  const essentialEndpointRows = endpointRows.slice(0, 4);

  const handleCopy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      window.setTimeout(() => setCopied((current) => (current === id ? null : current)), 1800);
    } catch {
      setCopied(null);
    }
  };

  return (
    <WorkspacePageFrame backHref="/dashboard" backLabel="Back to Workspace Overview">
      <div className="flex min-w-0 flex-col gap-5">
        <DashboardPageIntro icon={BookOpen} title="Developer Hub">
          Trigger audits programmatically, consume raw JSON reports, and wire completion callbacks
          into BI or workflow tooling.
        </DashboardPageIntro>

        <SignalTabs<DevTab> tabs={DEV_TABS} activeId={tab} onChange={setTab} />

        {tab === "hub" && (
          <SignalTabPanel id="hub" activeId={tab}>
            <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
              <div className="mb-4 flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                    API Access
                  </h3>
                  <p className="mt-[3px] mb-0 text-[12.5px] leading-[1.5] text-(--t-3)">
                    Current workspace status and throughput limits.
                  </p>
                </div>
                {apiEnabled ? (
                  <Link
                    href="/dashboard/settings"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                  >
                    Manage API Keys
                  </Link>
                ) : (
                  <Link
                    href="/dashboard/billing"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                  >
                    Upgrade for API Access
                  </Link>
                )}
              </div>
              <div className="flex gap-3.5 max-md:flex-col">
                <div className="flex-1 rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
                  <div className="mb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    API access
                  </div>
                  <div
                    className={cx(
                      "font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em]",
                      apiEnabled && "text-(--good)"
                    )}
                  >
                    {accessLabel}
                  </div>
                  <div className="mt-[3px] text-[11.5px] text-(--t-3)">{planName}</div>
                </div>
                <div className="flex-1 rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
                  <div className="mb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    Active keys
                  </div>
                  <div className="font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em]">
                    {loading ? "-" : activeKeyCount}
                  </div>
                  <div className="mt-[3px] text-[11.5px] text-(--t-3)">
                    Workspace-managed credentials
                  </div>
                </div>
                <div className="flex-1 rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
                  <div className="mb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    Throughput
                  </div>
                  <div className="font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em]">
                    {throughput.summary}
                  </div>
                  <div className="mt-[3px] text-[11.5px] text-(--t-3)">{throughput.detail}</div>
                </div>
              </div>
            </div>

            {payload && !apiEnabled ? (
              <PlanLockNotice
                {...planLockContent}
                title="API Access Locked"
                // SIGV2-1310: says what is locked and what is not.
                //
                // QA read this page as contradicting itself: the Hub says the
                // API is locked while the same page still offers Download
                // JSON. Both are true and both are deliberate. The download is
                // a product feature on every plan, kept that way on purpose
                // (see RawJsonReportCard) so moving it here did not silently
                // take it from plans that had it. What Specialist buys is
                // programmatic access: keys, and calling the API yourself.
                //
                // The old wording said "External API access" without naming
                // the download, so a reader had no way to tell the two apart.
                description="Creating API keys and calling the API yourself is available on Specialist and above. Upgrade in Billing, then create keys from Workspace Settings. Downloading a report as JSON stays available on your current plan, below."
                badgeLabel="Headless API"
              />
            ) : null}
            {error ? (
              <SignalAlert tone="danger" title="API access unavailable">
                {error}
              </SignalAlert>
            ) : null}
          </SignalTabPanel>
        )}

        {tab === "quickstart" && (
          <SignalTabPanel id="quickstart" activeId={tab}>
            <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
              <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                Quick Start
              </h3>
              <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
                Three steps from key creation to production delivery.
              </p>
              {quickStartSteps.map((item) => (
                <div
                  key={item.id}
                  className="flex gap-[13px] border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap"
                >
                  <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-(--ink) font-(family-name:--disp) text-[12px] font-bold text-white">
                    {item.n}
                  </span>
                  <div className="flex-1">
                    <div className="text-[13.5px] font-semibold">{item.title}</div>
                    <p className="m-0 text-[13px] leading-[1.5] text-(--t-2)">{item.description}</p>
                  </div>
                  <Link
                    href={item.href}
                    className="inline-flex h-[38px] cursor-pointer flex-none items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] max-md:w-full max-md:justify-center"
                  >
                    {item.action}
                  </Link>
                </div>
              ))}
            </div>
            <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                  Starter Request
                </h3>
                <button
                  className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                  onClick={() => void handleCopy("curl", codeSamples.curl)}
                >
                  {copied === "curl" ? "Copied" : "Copy"}
                </button>
              </div>
              <pre
                className="m-0 overflow-x-auto whitespace-pre rounded-[12px] bg-(--ink) px-[18px] py-4 font-(family-name:--mono) text-[12.5px] leading-[1.6] text-[#e6e9f0] max-md:max-w-full"
                role="region"
                aria-label="Starter API request"
                tabIndex={0}
              >
                <code className="rounded-[5px] bg-transparent p-0 font-(family-name:--mono) text-[12.5px]">
                  {codeSamples.curl}
                </code>
              </pre>
            </div>
          </SignalTabPanel>
        )}

        {tab === "reference" && (
          <SignalTabPanel id="reference" activeId={tab}>
            <div className="rounded-[22px] border-0 bg-white">
              <div className="flex items-center justify-between px-6 pt-[22px] pb-0">
                <div>
                  <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                    Key Endpoints
                  </h3>
                  <p className="m-0 text-[12.5px] leading-[1.5] text-(--t-3)">
                    Core routes most teams wire first.
                  </p>
                </div>
                <Link
                  href="/dashboard/developer/docs"
                  className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                >
                  Full Docs
                </Link>
              </div>
              <div
                className="max-md:max-w-full max-md:overflow-x-auto max-md:overscroll-x-contain max-md:[&>table]:min-w-[620px]"
                role="region"
                aria-label="Key API endpoints"
                tabIndex={0}
              >
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="w-20 border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Method
                      </th>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Path
                      </th>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Purpose
                      </th>
                    </tr>
                  </thead>
                  <tbody className="[&>tr:last-child>td]:border-b-0">
                    {essentialEndpointRows.map(([method, path, description]) => (
                      <tr key={path}>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          <span
                            className={cx(
                              "rounded-[6px] px-2 py-[3px] font-(family-name:--mono) text-[11px] font-semibold tracking-[0.04em]",
                              String(method).toLowerCase() === "get"
                                ? "bg-[rgba(37,99,235,0.1)] text-(--blue)"
                                : "bg-(--good-s) text-(--good)"
                            )}
                          >
                            {method}
                          </span>
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle font-(family-name:--mono) text-[12.5px]">
                          {path}
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          {description}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <RawJsonReportCard />
            <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
              <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                Webhook Delivery
              </h3>
              <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
                Pass{" "}
                <code className="rounded-[5px] bg-(--line-2) px-[5px] py-px font-(family-name:--mono) text-[12.5px]">
                  webhook_url
                </code>{" "}
                to receive signed completion payloads automatically.
              </p>
              <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                Signature header
              </span>
              <pre
                className="m-0 mb-4 overflow-x-auto whitespace-pre rounded-[12px] bg-(--ink) px-[18px] py-4 font-(family-name:--mono) text-[12.5px] leading-[1.6] text-[#e6e9f0] max-md:max-w-full"
                role="region"
                aria-label="Webhook signature header"
                tabIndex={0}
              >
                <code className="rounded-[5px] bg-transparent p-0 font-(family-name:--mono) text-[12.5px]">
                  X-Qiko-Signal-Signature: sha256=&lt;hex-digest&gt;
                </code>
              </pre>
              <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
                <div>
                  <div className="text-[13.5px] font-semibold">Verify every delivery</div>
                  <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
                    Recompute the HMAC over the raw request body using the one-time webhook_secret.
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
                <div>
                  <div className="text-[13.5px] font-semibold">Keep polling as fallback</div>
                  <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
                    Start with polling during setup, enable webhooks once signature checks are
                    ready.
                  </div>
                </div>
              </div>
            </div>
          </SignalTabPanel>
        )}

        {tab === "mcp" && (
          <SignalTabPanel id="mcp" activeId={tab}>
            <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
              <div className="mb-4 flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                    MCP Server
                  </h3>
                  <p className="mt-[3px] mb-0 text-[12.5px] leading-[1.5] text-(--t-3)">
                    Streamable HTTP, JSON-RPC 2.0. The same workspace API key authenticates it.
                  </p>
                </div>
                {mcpEnabled ? (
                  <Link
                    href="/dashboard/settings"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                  >
                    Manage API Keys
                  </Link>
                ) : (
                  <Link
                    href="/dashboard/billing"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                  >
                    Upgrade for MCP Access
                  </Link>
                )}
              </div>
              <div className="flex gap-3.5 max-md:flex-col">
                <div className="flex-1 rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
                  <div className="mb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    MCP access
                  </div>
                  <div
                    className={cx(
                      "font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em]",
                      mcpEnabled && "text-(--good)"
                    )}
                  >
                    {loading ? "Checking" : mcpEnabled ? "Enabled" : "Locked"}
                  </div>
                  <div className="mt-[3px] text-[11.5px] text-(--t-3)">
                    Available on Specialist and Executive
                  </div>
                </div>
                <div className="flex-1 rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
                  <div className="mb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    Endpoint
                  </div>
                  <div className="overflow-x-auto font-(family-name:--mono) text-[12px] font-semibold leading-[1.7]">
                    POST {mcpEndpointUrl}
                  </div>
                  <div className="mt-[3px] text-[11.5px] text-(--t-3)">
                    Stateless, POST-only, JSON responses
                  </div>
                </div>
                <div className="flex-1 rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
                  <div className="mb-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    Tools
                  </div>
                  <div className="font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em]">
                    {mcpToolRows.length}
                  </div>
                  <div className="mt-[3px] text-[11.5px] text-(--t-3)">
                    {mcpToolRows.length - 1} read, 1 spends a scan
                  </div>
                </div>
              </div>
            </div>

            {payload && !mcpEnabled ? (
              <PlanLockNotice {...mcpLockContent} badgeLabel="MCP Server" />
            ) : null}

            <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
              <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                Connect a Client
              </h3>
              <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
                Create a key in Workspace Settings, then use the config that matches your client.
              </p>
              <div className="mb-3 flex items-center justify-between">
                <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                  Streamable HTTP clients
                </span>
                <button
                  className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                  onClick={() => void handleCopy("mcp-http", mcpSamples.httpConfig)}
                >
                  {copied === "mcp-http" ? "Copied" : "Copy"}
                </button>
              </div>
              <pre
                className="m-0 mb-4 overflow-x-auto whitespace-pre rounded-[12px] bg-(--ink) px-[18px] py-4 font-(family-name:--mono) text-[12.5px] leading-[1.6] text-[#e6e9f0] max-md:max-w-full"
                role="region"
                aria-label="MCP HTTP client configuration"
                tabIndex={0}
              >
                <code className="rounded-[5px] bg-transparent p-0 font-(family-name:--mono) text-[12.5px]">
                  {mcpSamples.httpConfig}
                </code>
              </pre>
              <div className="mb-3 flex items-center justify-between">
                <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                  Stdio clients (bridge)
                </span>
                <button
                  className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                  onClick={() => void handleCopy("mcp-stdio", mcpClaudeDesktopConfig)}
                >
                  {copied === "mcp-stdio" ? "Copied" : "Copy"}
                </button>
              </div>
              <pre
                className="m-0 mb-4 overflow-x-auto whitespace-pre rounded-[12px] bg-(--ink) px-[18px] py-4 font-(family-name:--mono) text-[12.5px] leading-[1.6] text-[#e6e9f0] max-md:max-w-full"
                role="region"
                aria-label="MCP stdio bridge configuration"
                tabIndex={0}
              >
                <code className="rounded-[5px] bg-transparent p-0 font-(family-name:--mono) text-[12.5px]">
                  {mcpClaudeDesktopConfig}
                </code>
              </pre>
              <p className="m-0 mb-[18px] text-[12px] leading-[1.45] text-(--t-3)">
                Clients that only speak stdio use{" "}
                <code className="rounded-[5px] bg-(--line-2) px-[5px] py-px font-(family-name:--mono) text-[12px]">
                  scripts/mcp_stdio_bridge.py
                </code>{" "}
                from the repo; it forwards to the same endpoint and defaults to production. Point it
                elsewhere with{" "}
                <code className="rounded-[5px] bg-(--line-2) px-[5px] py-px font-(family-name:--mono) text-[12px]">
                  QIKO_SIGNAL_MCP_URL
                </code>
                .
              </p>
              <div className="mb-3 flex items-center justify-between">
                <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                  Verify with curl
                </span>
                <button
                  className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                  onClick={() => void handleCopy("mcp-init", mcpSamples.initialize)}
                >
                  {copied === "mcp-init" ? "Copied" : "Copy"}
                </button>
              </div>
              <pre
                className="m-0 overflow-x-auto whitespace-pre rounded-[12px] bg-(--ink) px-[18px] py-4 font-(family-name:--mono) text-[12.5px] leading-[1.6] text-[#e6e9f0] max-md:max-w-full"
                role="region"
                aria-label="MCP initialize request"
                tabIndex={0}
              >
                <code className="rounded-[5px] bg-transparent p-0 font-(family-name:--mono) text-[12.5px]">
                  {mcpSamples.initialize}
                </code>
              </pre>
            </div>

            <div className="rounded-[22px] border-0 bg-white">
              <div className="px-6 pt-[22px] pb-0">
                <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                  Tool Catalogue
                </h3>
                <p className="m-0 text-[12.5px] leading-[1.5] text-(--t-3)">
                  One catalogue, no pagination. Every tool but the last only reads;{" "}
                  <code className="rounded-[5px] bg-(--line-2) px-[5px] py-px font-(family-name:--mono) text-[12px]">
                    signal_run_audit
                  </code>{" "}
                  consumes one scan from the plan allowance and needs the{" "}
                  <code className="rounded-[5px] bg-(--line-2) px-[5px] py-px font-(family-name:--mono) text-[12px]">
                    audit:write
                  </code>{" "}
                  scope, which new keys do not get by default.
                </p>
              </div>
              <div
                className="max-md:max-w-full max-md:overflow-x-auto max-md:overscroll-x-contain max-md:[&>table]:min-w-[620px]"
                role="region"
                aria-label="MCP tools"
                tabIndex={0}
              >
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Tool
                      </th>
                      <th className="w-36 border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Scope
                      </th>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Purpose
                      </th>
                    </tr>
                  </thead>
                  <tbody className="[&>tr:last-child>td]:border-b-0">
                    {mcpToolRows.map(([tool, scope, purpose]) => (
                      <tr key={tool}>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle font-(family-name:--mono) text-[12.5px]">
                          {tool}
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          <span
                            className={cx(
                              "rounded-[6px] px-2 py-[3px] font-(family-name:--mono) text-[11px] font-semibold tracking-[0.04em]",
                              scope === "audit:write"
                                ? "bg-(--warn-s) text-(--warn)"
                                : "bg-[rgba(37,99,235,0.1)] text-(--blue)"
                            )}
                          >
                            {scope}
                          </span>
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          {purpose}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </SignalTabPanel>
        )}
      </div>
    </WorkspacePageFrame>
  );
}
