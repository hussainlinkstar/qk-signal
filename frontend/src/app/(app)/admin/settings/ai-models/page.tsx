"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Bot,
  Key,
  Search,
  Save,
  RefreshCcw,
  CheckCircle2,
  AlertTriangle,
  Eye,
  EyeOff,
  Server,
  Cpu,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import Button from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";

const CARD = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 mb-[3px] flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const CARD_DESC = "mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)";
const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border border-(--line) bg-(--paper) px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const CODE =
  "rounded-(--r-sm) bg-(--line-2) px-1 font-(family-name:--mono) text-[11.5px] text-(--t-1)";

// ── Types ─────────────────────────────────────────────────────────────────────

type AiProviderKeys = {
  firecrawl_api_key?: string;
  pagespeed_api_key?: string;
  search_api_key?: string;
  serpapi_api_key?: string;
  google_places_api_key?: string;
  google_maps_api_key?: string;
  dataforseo_login?: string;
  dataforseo_password?: string;
};

type SearchConfig = {
  serpapi_engine?: string;
  google_places_api_mode?: string;
  google_places_fallback_to_legacy?: boolean;
};

// The engine runs reasoning/measurement/embeddings/support-chat/pre-scan/
// case-study entirely on AWS Bedrock. Only the Bedrock tier models are editable.
type ModelRouting = {
  BEDROCK_SMART_MODEL?: string;
  BEDROCK_FAST_MODEL?: string;
  BEDROCK_LITE_MODEL?: string;
  BEDROCK_EMBEDDING_MODEL?: string;
};

type BedrockStatus = {
  configured?: boolean;
  region?: string;
  enabled?: boolean;
};

type AiProvidersData = {
  ai_provider_keys: AiProviderKeys;
  search_config: SearchConfig;
  model_routing: ModelRouting;
  bedrock_status: BedrockStatus;
  measurement_model_map: Record<string, string>;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function isMasked(val?: string): boolean {
  return typeof val === "string" && val.startsWith("****");
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SecretInput({
  label,
  fieldKey,
  value,
  onChange,
}: {
  label: string;
  fieldKey: string;
  value: string;
  onChange: (key: string, val: string) => void;
}) {
  const [show, setShow] = useState(false);
  const masked = isMasked(value);

  return (
    <div>
      <label htmlFor={fieldKey} className={FIELD_LABEL}>
        {label}
      </label>
      <div className="relative flex items-center">
        <input
          id={fieldKey}
          type={show ? "text" : "password"}
          value={masked && !show ? "" : value}
          placeholder={
            masked && !show
              ? "••••••••  (set, enter new value to update)"
              : "Not set, falls back to .env"
          }
          className={`${WINPUT} pr-10`}
          onChange={(e) => onChange(fieldKey, e.target.value)}
        />
        <button
          type="button"
          className="absolute right-3 text-(--t-3) hover:text-(--t-1)"
          onClick={() => setShow((v) => !v)}
          tabIndex={-1}
          aria-label={show ? "Hide secret" : "Show secret"}
        >
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
      {masked && (
        <p className="mt-1 flex items-center gap-1 text-[12.5px] text-(--good)">
          <CheckCircle2 size={11} /> Configured in database
        </p>
      )}
    </div>
  );
}

function SelectInput({
  label,
  fieldKey,
  value,
  options,
  onChange,
}: {
  label: string;
  fieldKey: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (key: string, val: string) => void;
}) {
  return (
    <div>
      <label htmlFor={fieldKey} className={FIELD_LABEL}>
        {label}
      </label>
      <NativeSelect
        id={fieldKey}
        variant="auth"
        value={value}
        onChange={(e) => onChange(fieldKey, e.target.value)}
      >
        <option value="">, env default, </option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AiModelsPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [data, setData] = useState<AiProvidersData | null>(null);
  const [keysDraft, setKeysDraft] = useState<Record<string, string>>({});
  const [searchDraft, setSearchDraft] = useState<Record<string, string>>({});
  const [modelDraft, setModelDraft] = useState<Record<string, string>>({});

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const res = await fetch("/api/admin/settings/ai-providers", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(await res.text());
      const json: AiProvidersData = await res.json();
      setData(json);
      // Pre-fill drafts with masked/current values
      setKeysDraft(
        Object.fromEntries(Object.entries(json.ai_provider_keys).map(([k, v]) => [k, v ?? ""]))
      );
      setSearchDraft(
        Object.fromEntries(Object.entries(json.search_config).map(([k, v]) => [k, String(v ?? "")]))
      );
      setModelDraft(
        Object.fromEntries(Object.entries(json.model_routing).map(([k, v]) => [k, String(v ?? "")]))
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [isSignedIn, getToken]);

  useEffect(() => {
    if (!isGuardLoading && isAdmin) fetchData();
  }, [isGuardLoading, isAdmin, fetchData]);

  const handleKeyChange = (key: string, val: string) =>
    setKeysDraft((prev) => ({ ...prev, [key]: val }));

  const handleSearchChange = (key: string, val: string) =>
    setSearchDraft((prev) => ({ ...prev, [key]: val }));

  const handleModelChange = (key: string, val: string) =>
    setModelDraft((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const token = await getToken();

      // Save API keys (omit empty strings, they represent "no change")
      const keysPayload = Object.fromEntries(
        Object.entries(keysDraft).filter(([, v]) => v !== "" && !isMasked(v))
      );
      // Save search config
      const searchPayload = Object.fromEntries(
        Object.entries(searchDraft).filter(([, v]) => v !== "")
      );

      await fetch("/api/admin/settings/ai-providers/bulk", {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          keys: Object.keys(keysPayload).length ? keysPayload : undefined,
          search: Object.keys(searchPayload).length ? searchPayload : undefined,
        }),
      });

      // Save model routing via runtime config endpoint
      const modelUpdates = Object.fromEntries(
        Object.entries(modelDraft).filter(([, v]) => v !== "")
      );
      if (Object.keys(modelUpdates).length > 0) {
        await fetch("/api/admin/config", {
          method: "PATCH",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ updates: modelUpdates }),
        });
      }

      setSavedAt(new Date().toLocaleTimeString());
      await fetchData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const { setHeader } = useWorkspacePageHeader();
  const actionsRef = useRef({ fetchData, handleSave });
  actionsRef.current = { fetchData, handleSave };
  useEffect(() => {
    setHeader({
      actions: isAdmin ? (
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void actionsRef.current.fetchData()}
            disabled={loading}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCcw size={14} className={loading ? "animate-spin" : ""} />
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void actionsRef.current.handleSave()}
            disabled={saving}
          >
            <Save size={14} />
            <span className="max-sm:hidden">{saving ? "Saving…" : "Save All"}</span>
          </Button>
        </>
      ) : null,
    });
    return () => setHeader(null);
  }, [isAdmin, loading, saving, setHeader]);

  if (isGuardLoading || loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[13px] text-(--t-3)">
        Loading AI Models configuration…
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[13px] text-(--bad)">
        Access denied.
      </div>
    );
  }

  return (
    <>
      <DashboardPageIntro icon={Bot} title="AI models &amp; provider keys">
        Values stored here take priority over <code className={CODE}>.env</code> / AWS SSM. Leave a
        field blank to keep the current env value.
      </DashboardPageIntro>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {savedAt && (
        <Alert variant="success">
          <CheckCircle2 />
          <AlertDescription>Saved at {savedAt}</AlertDescription>
        </Alert>
      )}

      {/* API Keys */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>
          <Key size={15} className="text-(--purple)" />
          Provider API Keys
        </h2>
        <p className={CARD_DESC}>
          Reasoning and CMS content generation run on AWS Bedrock (no LLM keys needed). These are
          data-provider keys only.
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {(
            [
              ["firecrawl_api_key", "Firecrawl API Key"],
              ["serpapi_api_key", "SerpAPI Key"],
              ["pagespeed_api_key", "PageSpeed API Key"],
              ["google_places_api_key", "Google Places API Key"],
              ["google_maps_api_key", "Google Maps API Key"],
              ["search_api_key", "Search API Key"],
              ["dataforseo_login", "DataForSEO Login"],
              ["dataforseo_password", "DataForSEO Password"],
            ] as [string, string][]
          ).map(([k, label]) => (
            <SecretInput
              key={k}
              label={label}
              fieldKey={k}
              value={keysDraft[k] ?? ""}
              onChange={handleKeyChange}
            />
          ))}
        </div>
      </section>

      {/* Search Config */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>
          <Search size={15} className="text-(--purple)" />
          Search Configuration
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <SelectInput
            label="SerpAPI Engine"
            fieldKey="serpapi_engine"
            value={searchDraft.serpapi_engine ?? ""}
            options={[
              { value: "google", label: "Google" },
              { value: "bing", label: "Bing" },
              { value: "duckduckgo", label: "DuckDuckGo" },
            ]}
            onChange={handleSearchChange}
          />
          <SelectInput
            label="Google Places API Mode"
            fieldKey="google_places_api_mode"
            value={searchDraft.google_places_api_mode ?? ""}
            options={[
              { value: "new", label: "New API" },
              { value: "legacy", label: "Legacy API" },
            ]}
            onChange={handleSearchChange}
          />
          <div>
            <span className={FIELD_LABEL}>Fallback to Legacy Places</span>
            <label className="flex h-11 cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={searchDraft.google_places_fallback_to_legacy === "true"}
                className="h-[17px] w-[17px] rounded-[5px] accent-(--ink)"
                onChange={(e) =>
                  handleSearchChange(
                    "google_places_fallback_to_legacy",
                    e.target.checked ? "true" : "false"
                  )
                }
              />
              <span className="text-[13px] text-(--t-1)">
                Allow fallback to legacy Google Places API
              </span>
            </label>
          </div>
        </div>
      </section>

      {/* Bedrock Credential Status (read-only) */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>
          <Server size={15} className="text-(--purple)" />
          AWS Bedrock Status
        </h2>
        <p className={CARD_DESC}>
          The reasoning engine runs entirely on AWS Bedrock. The credential (
          <code className={CODE}>AWS_BEARER_TOKEN_BEDROCK</code>) is managed via AWS SSM and is
          read-only here: its value is never exposed.
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <span className={FIELD_LABEL}>Credential</span>
            {data?.bedrock_status?.configured ? (
              <span className="flex items-center gap-1 text-[13px] text-(--good)">
                <CheckCircle2 size={13} /> Configured
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[13px] text-(--bad)">
                <AlertTriangle size={13} /> Not configured
              </span>
            )}
          </div>
          <div>
            <span className={FIELD_LABEL}>Region</span>
            <span className="text-[13px] text-(--t-1)">
              {data?.bedrock_status?.region || "N/A"}
            </span>
          </div>
          <div>
            <span className={FIELD_LABEL}>Enabled</span>
            <span className="text-[13px] text-(--t-1)">
              {data?.bedrock_status?.enabled ? "Yes" : "No"}
            </span>
          </div>
        </div>
      </section>

      {/* Bedrock Model Routing (editable) */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>
          <Bot size={15} className="text-(--purple)" />
          Bedrock Model Routing (Runtime Config)
        </h2>
        <p className={CARD_DESC}>
          Stored in runtime_config, take effect within 30 seconds without restart. These models
          drive reasoning, measurement, embeddings, support chat, pre-scan and case-study
          generation.
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {(
            [
              [
                "BEDROCK_SMART_MODEL",
                "Smart Model (deep reasoning / synthesis)",
                ["eu.anthropic.claude-sonnet-4-5-20250929-v1:0", "eu.amazon.nova-pro-v1:0"],
              ],
              [
                "BEDROCK_FAST_MODEL",
                "Fast Model (debate / standard reasoning)",
                [
                  "eu.amazon.nova-lite-v1:0",
                  "eu.amazon.nova-pro-v1:0",
                  "eu.amazon.nova-micro-v1:0",
                ],
              ],
              [
                "BEDROCK_LITE_MODEL",
                "Lite Model (pre-scan / classification)",
                ["eu.amazon.nova-micro-v1:0", "eu.amazon.nova-lite-v1:0"],
              ],
              [
                "BEDROCK_EMBEDDING_MODEL",
                "Embedding Model",
                ["eu.cohere.embed-v4:0", "eu.amazon.titan-embed-text-v2:0"],
              ],
            ] as [string, string, string[]][]
          ).map(([k, label, opts]) => (
            <SelectInput
              key={k}
              label={label}
              fieldKey={k}
              value={modelDraft[k] ?? ""}
              options={opts.map((o) => ({ value: o, label: o }))}
              onChange={handleModelChange}
            />
          ))}
        </div>
      </section>

      {/* Bedrock Measurement Model Map (read-only) */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>
          <Cpu size={15} className="text-(--purple)" />
          Measurement Model Map
        </h2>
        <p className={CARD_DESC}>
          Read-only. Each visibility &ldquo;engine&rdquo; is mapped to a Bedrock model id.
          Configured via <code className={CODE}>BEDROCK_MEASUREMENT_MODEL_MAP</code> (env/SSM).
        </p>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {Object.entries(data?.measurement_model_map ?? {}).map(([provider, model]) => (
            <div
              key={provider}
              className="flex items-center justify-between gap-2 rounded-(--r-sm) border border-(--line) bg-(--paper) px-3 py-2"
            >
              <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                {provider}
              </span>
              <span
                className="truncate font-(family-name:--mono) text-[11.5px] text-(--t-2)"
                title={model}
              >
                {model}
              </span>
            </div>
          ))}
          {Object.keys(data?.measurement_model_map ?? {}).length === 0 && (
            <p className="text-[12.5px] text-(--t-3)">No measurement model map configured.</p>
          )}
        </div>
      </section>

      {data && (
        <p className="text-right font-(family-name:--mono) text-[11.5px] text-(--t-3)">
          Resolution: DB override → .env / AWS SSM → Settings default
        </p>
      )}
    </>
  );
}
