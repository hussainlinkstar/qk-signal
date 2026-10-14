"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Lock, Save, RefreshCcw, CheckCircle2, AlertTriangle, Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import Button from "@/components/ui/Button";
import { Alert, AlertDescription } from "@/components/ui/alert";

const CARD = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 mb-[14px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border border-(--line) bg-(--paper) px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const CODE =
  "rounded-(--r-sm) bg-(--line-2) px-1 font-(family-name:--mono) text-[11.5px] text-(--t-1)";

// ── Types ─────────────────────────────────────────────────────────────────────

type OAuthConfig = {
  google_client_id?: string;
  google_client_secret?: string;
  github_client_id?: string;
  github_client_secret?: string;
  linkedin_client_id?: string;
  linkedin_client_secret?: string;
  jira_client_id?: string;
  jira_client_secret?: string;
  bing_client_id?: string;
  bing_client_secret?: string;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function isMasked(val?: string): boolean {
  return typeof val === "string" && val.startsWith("****");
}

// ── Sub-components ────────────────────────────────────────────────────────────

function OAuthProviderCard({
  provider,
  fields,
  draft,
  onChange,
}: {
  provider: string;
  fields: { key: string; label: string; secret?: boolean }[];
  draft: Record<string, string>;
  onChange: (key: string, val: string) => void;
}) {
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});

  const toggleShow = (key: string) => setShowSecrets((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>{provider}</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {fields.map(({ key, label, secret }) => {
          const val = draft[key] ?? "";
          const masked = isMasked(val);
          const show = showSecrets[key] ?? false;
          const fieldId = `oauth-${provider.toLowerCase().replace(/\s+/g, "-")}-${label.toLowerCase().replace(/\s+/g, "-")}`;

          return (
            <div key={key}>
              <label htmlFor={fieldId} className={FIELD_LABEL}>
                {label}
              </label>
              <div className="relative flex items-center">
                <input
                  id={fieldId}
                  type={secret && !show ? "password" : "text"}
                  value={masked && !show ? "" : val}
                  placeholder={
                    masked && !show
                      ? "••••••••  (set, enter new value to update)"
                      : "Not set, falls back to .env"
                  }
                  className={`${WINPUT} pr-10`}
                  onChange={(e) => onChange(key, e.target.value)}
                />
                {secret && (
                  <button
                    type="button"
                    className="absolute right-3 text-(--t-3) hover:text-(--t-1)"
                    onClick={() => toggleShow(key)}
                    tabIndex={-1}
                    aria-label={show ? "Hide secret" : "Show secret"}
                  >
                    {show ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                )}
              </div>
              {masked && (
                <p className="mt-1 flex items-center gap-1 text-[12.5px] text-(--good)">
                  <CheckCircle2 size={11} /> Configured in database
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const PROVIDERS = [
  {
    provider: "Google OAuth",
    fields: [
      { key: "google_client_id", label: "Client ID" },
      { key: "google_client_secret", label: "Client Secret", secret: true },
    ],
  },
  {
    provider: "GitHub OAuth",
    fields: [
      { key: "github_client_id", label: "Client ID" },
      { key: "github_client_secret", label: "Client Secret", secret: true },
    ],
  },
  {
    provider: "LinkedIn OAuth",
    fields: [
      { key: "linkedin_client_id", label: "Client ID" },
      { key: "linkedin_client_secret", label: "Client Secret", secret: true },
    ],
  },
  {
    provider: "Jira OAuth",
    fields: [
      { key: "jira_client_id", label: "Client ID" },
      { key: "jira_client_secret", label: "Client Secret", secret: true },
    ],
  },
  {
    provider: "Bing / Microsoft OAuth",
    fields: [
      { key: "bing_client_id", label: "Client ID" },
      { key: "bing_client_secret", label: "Client Secret", secret: true },
    ],
  },
];

export default function OAuthPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [draft, setDraft] = useState<Record<string, string>>({});
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
      const res = await fetch("/api/admin/settings/oauth", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(await res.text());
      const json: OAuthConfig = await res.json();
      setDraft(Object.fromEntries(Object.entries(json).map(([k, v]) => [k, v ?? ""])));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [isSignedIn, getToken]);

  useEffect(() => {
    if (!isGuardLoading && isAdmin) fetchData();
  }, [isGuardLoading, isAdmin, fetchData]);

  const handleChange = (key: string, val: string) => setDraft((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const token = await getToken();
      // Only send fields that changed (not masked, not empty)
      const payload = Object.fromEntries(
        Object.entries(draft).filter(([, v]) => v !== "" && !isMasked(v))
      );
      if (Object.keys(payload).length === 0) {
        setSavedAt("No changes");
        return;
      }
      const res = await fetch("/api/admin/settings/oauth", {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
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
        Loading OAuth configuration…
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
      <DashboardPageIntro icon={Lock} title="OAuth clients">
        OAuth client IDs and secrets stored in the database take priority over{" "}
        <code className={CODE}>.env</code>. Leave blank to keep the current env value.
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
          <AlertDescription>
            {savedAt === "No changes" ? "No changes to save." : `Saved at ${savedAt}`}
          </AlertDescription>
        </Alert>
      )}

      {PROVIDERS.map(({ provider, fields }) => (
        <OAuthProviderCard
          key={provider}
          provider={provider}
          fields={fields}
          draft={draft}
          onChange={handleChange}
        />
      ))}

      <p className="text-right font-(family-name:--mono) text-[11.5px] text-(--t-3)">
        Resolution: DB override → .env / AWS SSM → Settings default
      </p>
    </>
  );
}
