"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Check, Copy, Radar } from "lucide-react";

import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import Button from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";
import { CARD_LABEL_CLASS } from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import { cx } from "@/components/ui/utils";
import DeveloperSectionNav from "../DeveloperSectionNav";
import {
  codeSamples,
  mcpAuthSnippet,
  mcpClaudeDesktopConfig,
  mcpEndpointRows,
  type SampleKey,
} from "../content";

const authSnippet = `Authorization: Bearer stx_live_your_key
X-API-Key: stx_live_your_key
X-Request-ID: audit-demo-001`;

const requestExample = `{
  "url": "https://example.com",
  "tier": "fast",
  "project_id": 42,
  "idempotency_key": "audit-demo-001",
  "webhook_url": "https://agency.example/hooks/audit"
}`;

const responseExample = `{
  "job_id": "uuid-xxxx",
  "status": "queued",
  "estimated_completion_seconds": 45,
  "poll_url": "/api/v1/external/audit/uuid-xxxx",
  "webhook_secret": "one-time-secret"
}`;

const errorExample = `{
  "error": {
    "code": "SCAN_LIMIT_EXCEEDED",
    "message": "Scan limit reached (10/10 scans in the current 30-day window). Please upgrade your plan for more scans.",
    "status": 402
  }
}`;

const webhookExample = `X-Qiko-Signal-Signature: sha256=<hex-digest>

Compute the HMAC over the raw JSON body using the one-time webhook_secret
returned when the audit job was created.`;

const sampleTabs: { key: SampleKey; label: string }[] = [
  { key: "curl", label: "cURL" },
  { key: "python", label: "Python" },
  { key: "node", label: "Node" },
];

const tabClass = "rounded px-3 py-1.5 text-xs font-medium transition-colors";

function CopyButton({
  token,
  value,
  copiedToken,
  onCopy,
}: {
  token: string;
  value: string;
  copiedToken: string | null;
  onCopy: (token: string, value: string) => void;
}) {
  const copied = copiedToken === token;
  return (
    <Button
      variant="ghost"
      size="sm"
      className="shrink-0"
      onClick={() => void onCopy(token, value)}
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

export default function DeveloperDocsPage() {
  const [activeSample, setActiveSample] = useState<SampleKey>("curl");
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  const handleCopy = async (token: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedToken(token);
      window.setTimeout(() => {
        setCopiedToken((current) => (current === token ? null : current));
      }, 1800);
    } catch {
      setCopiedToken(null);
    }
  };

  return (
    <div className="dashboard-page-shell space-y-6">
      <DashboardPageIntro icon={Radar} title="Developer Docs" color="var(--primary)">
        Quick-start guide for the Qiko Signal Headless API, authentication, payloads, delivery, and
        code samples.
      </DashboardPageIntro>

      <DeveloperSectionNav />

      {/* Authentication + Create Request */}
      <div className="grid gap-3 xl:grid-cols-2">
        <GlassCard className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
            <h2 className={TYPO.cardTitle}>Authentication Headers</h2>
            <CopyButton
              token="auth"
              value={authSnippet}
              copiedToken={copiedToken}
              onCopy={handleCopy}
            />
          </div>
          <pre className="custom-scrollbar overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
            <code>{authSnippet}</code>
          </pre>
        </GlassCard>

        <GlassCard className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
            <h2 className={TYPO.cardTitle}>Create Audit Request</h2>
            <CopyButton
              token="request"
              value={requestExample}
              copiedToken={copiedToken}
              onCopy={handleCopy}
            />
          </div>
          <pre className="custom-scrollbar overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
            <code>{requestExample}</code>
          </pre>
        </GlassCard>
      </div>

      {/* Response + Error */}
      <div className="grid gap-3 xl:grid-cols-2">
        <GlassCard className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
            <h2 className={TYPO.cardTitle}>Response Format</h2>
            <CopyButton
              token="response"
              value={responseExample}
              copiedToken={copiedToken}
              onCopy={handleCopy}
            />
          </div>
          <pre className="custom-scrollbar overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
            <code>{responseExample}</code>
          </pre>
        </GlassCard>

        <GlassCard className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
            <h2 className={TYPO.cardTitle}>Error Envelope</h2>
            <CopyButton
              token="error"
              value={errorExample}
              copiedToken={copiedToken}
              onCopy={handleCopy}
            />
          </div>
          <pre className="custom-scrollbar overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
            <code>{errorExample}</code>
          </pre>
        </GlassCard>
      </div>

      {/* Webhook Verification */}
      <GlassCard className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
          <h2 className={TYPO.cardTitle}>Webhook Verification</h2>
          <CopyButton
            token="webhook"
            value={webhookExample}
            copiedToken={copiedToken}
            onCopy={handleCopy}
          />
        </div>
        <pre className="custom-scrollbar overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
          <code>{webhookExample}</code>
        </pre>
      </GlassCard>

      {/* Operational Rules */}
      <div>
        <h2 className={TYPO.cardTitle}>Operational Rules</h2>
        <p className="mt-0.5 text-sm text-(--muted-foreground)">
          Rate limits, idempotency, and delivery contract.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <GlassCard className="px-4 py-3.5">
          <p className={CARD_LABEL_CLASS}>Rate Limits</p>
          <div className="mt-1.5 space-y-1 text-sm text-(--muted-foreground)">
            <p>
              <span className="text-(--foreground)">Specialist</span>: 60 req/min, 1k/day
            </p>
            <p>
              <span className="text-(--foreground)">Executive</span>: 300 req/min, 10k/day
            </p>
          </div>
        </GlassCard>
        <GlassCard className="px-4 py-3.5">
          <p className={CARD_LABEL_CLASS}>Idempotency</p>
          <p className="mt-1.5 text-sm text-(--muted-foreground)">
            Include a client-generated{" "}
            <code className="rounded bg-white/5 px-1 py-0.5 text-(--foreground)">
              idempotency_key
            </code>{" "}
            (any unique string, e.g. a UUID) in the request body. The server deduplicates matching
            submissions for 24 hours, making retries safe.
          </p>
        </GlassCard>
        <GlassCard className="px-4 py-3.5">
          <p className={CARD_LABEL_CLASS}>Traceability</p>
          <p className="mt-1.5 text-sm text-(--muted-foreground)">
            Every response includes X-Request-ID and rate-limit headers. Webhook-enabled submissions
            return a one-time webhook_secret.
          </p>
        </GlassCard>
      </div>

      {/* Code Samples */}
      <GlassCard className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
          <h2 className={TYPO.cardTitle}>Code Samples</h2>
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {sampleTabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveSample(tab.key)}
                  className={cx(
                    tabClass,
                    activeSample === tab.key
                      ? "border border-primary/20 bg-primary/10 text-primary"
                      : "text-(--muted-foreground) hover:bg-(--surface-subtle) hover:text-(--foreground)"
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <CopyButton
              token={`sample-${activeSample}`}
              value={codeSamples[activeSample]}
              copiedToken={copiedToken}
              onCopy={handleCopy}
            />
          </div>
        </div>
        <pre className="custom-scrollbar overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
          <code>{codeSamples[activeSample]}</code>
        </pre>
      </GlassCard>

      {/* MCP Connection */}
      <div>
        <h2 className={TYPO.cardTitle}>Connect an MCP Client</h2>
        <p className="mt-0.5 text-sm text-(--muted-foreground)">
          Give Claude, ChatGPT, or another MCP-capable client read access to your projects, audits,
          recommendations, competitors, schedules, and alerts, and let it start new audits on your
          behalf.
        </p>
      </div>

      <GlassCard className="px-4 py-3.5">
        <p className={CARD_LABEL_CLASS}>Requirements</p>
        <p className="mt-1.5 text-sm text-(--muted-foreground)">
          MCP access requires an active Specialist or Executive plan and a Qiko Signal API key.
          Create one from{" "}
          <Link href="/dashboard/settings" className="text-primary underline underline-offset-2">
            Workspace Settings &rarr; API Keys
          </Link>
          . Keys created from that form are read-only; to enable{" "}
          <code className="rounded bg-white/5 px-1 py-0.5 text-(--foreground)">
            signal_run_audit
          </code>
          , create a key with the{" "}
          <code className="rounded bg-white/5 px-1 py-0.5 text-(--foreground)">audit:write</code>{" "}
          scope via{" "}
          <code className="rounded bg-white/5 px-1 py-0.5 text-(--foreground)">
            POST /api/v1/settings/api-keys
          </code>
          .
        </p>
      </GlassCard>

      <div className="grid gap-3 xl:grid-cols-2">
        <GlassCard className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
            <h2 className={TYPO.cardTitle}>MCP Endpoint</h2>
            <CopyButton
              token="mcp-endpoint"
              value={mcpEndpointRows[0][1]}
              copiedToken={copiedToken}
              onCopy={handleCopy}
            />
          </div>
          <div className="px-4 py-3 text-sm">
            <table className="w-full text-left">
              <tbody>
                {mcpEndpointRows.map(([label, url]) => (
                  <tr key={label} className="border-b border-(--border) last:border-0">
                    <td className="py-2 pr-3 align-top text-(--muted-foreground)">{label}</td>
                    <td className="py-2 font-mono text-xs break-all text-(--text-soft)">{url}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-(--muted-foreground)">
              Streamable HTTP, JSON-RPC 2.0. Authenticate every request; there is no separate login
              step.
            </p>
          </div>
        </GlassCard>

        <GlassCard className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
            <h2 className={TYPO.cardTitle}>Authentication Header</h2>
            <CopyButton
              token="mcp-auth"
              value={mcpAuthSnippet}
              copiedToken={copiedToken}
              onCopy={handleCopy}
            />
          </div>
          <pre className="custom-scrollbar overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
            <code>{mcpAuthSnippet}</code>
          </pre>
        </GlassCard>
      </div>

      <GlassCard className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-(--border) px-4 py-2.5">
          <h2 className={TYPO.cardTitle}>Claude Desktop</h2>
          <CopyButton
            token="mcp-claude"
            value={mcpClaudeDesktopConfig}
            copiedToken={copiedToken}
            onCopy={handleCopy}
          />
        </div>
        <div className="px-4 py-3">
          <p className="text-sm text-(--muted-foreground)">
            Claude Desktop talks to MCP servers over stdio, not plain HTTP. Download the
            repository&apos;s{" "}
            <a
              href="https://github.com/Qiko-AILabs/qiko-signal/blob/main/scripts/mcp_stdio_bridge.py"
              target="_blank"
              rel="noreferrer"
              className="text-primary underline underline-offset-2"
            >
              <code className="rounded bg-white/5 px-1 py-0.5 text-(--foreground)">
                mcp_stdio_bridge.py
              </code>
            </a>{" "}
            (standard-library Python 3, no install step), save it locally, then add this block to
            your{" "}
            <code className="rounded bg-white/5 px-1 py-0.5 text-(--foreground)">
              claude_desktop_config.json
            </code>
            , updating the script path and API key:
          </p>
          <pre className="custom-scrollbar mt-3 overflow-x-auto rounded bg-black/20 px-4 py-3 font-mono text-sm leading-relaxed text-(--text-soft)">
            <code>{mcpClaudeDesktopConfig}</code>
          </pre>
          <p className="mt-3 text-sm text-(--muted-foreground)">
            Restart Claude Desktop afterward. The bridge forwards every request to the hosted
            endpoint above; plan checks, scopes, and rate limits are still enforced on the server.
          </p>
        </div>
      </GlassCard>

      <GlassCard className="px-4 py-3.5">
        <p className={CARD_LABEL_CLASS}>ChatGPT</p>
        <p className="mt-1.5 text-sm text-(--muted-foreground)">
          ChatGPT&apos;s support for connecting to a custom remote MCP server (via custom connectors
          / the Apps SDK) depends on your OpenAI plan and whether that feature is enabled for your
          workspace, and it continues to change. Check{" "}
          <a
            href="https://platform.openai.com/docs/mcp"
            target="_blank"
            rel="noreferrer"
            className="text-primary underline underline-offset-2"
          >
            OpenAI&apos;s current MCP connector documentation
          </a>{" "}
          for the exact steps in your account. Where a custom connector accepts an HTTP endpoint and
          a bearer token, use the MCP endpoint and API key above the same way as any other MCP
          client.
        </p>
      </GlassCard>
    </div>
  );
}
