"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Mail, Save, RefreshCcw, CheckCircle2, AlertTriangle, Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import Button from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 mb-[14px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const CODE =
  "rounded-(--r-sm) bg-(--line-2) px-1 font-(family-name:--mono) text-[11.5px] text-(--t-1)";

// ── Types ─────────────────────────────────────────────────────────────────────

type EmailConfig = {
  enabled?: boolean;
  provider?: string;
  from_address?: string;
  from_name?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_username?: string;
  smtp_password?: string;
  outbox_max_attempts?: number;
  outbox_batch_size?: number;
};

type Draft = {
  enabled: string;
  provider: string;
  from_address: string;
  from_name: string;
  smtp_host: string;
  smtp_port: string;
  smtp_username: string;
  smtp_password: string;
  outbox_max_attempts: string;
  outbox_batch_size: string;
};

function isMasked(val: string): boolean {
  return val.startsWith("****");
}

const EMPTY_DRAFT: Draft = {
  enabled: "",
  provider: "",
  from_address: "",
  from_name: "",
  smtp_host: "",
  smtp_port: "",
  smtp_username: "",
  smtp_password: "",
  outbox_max_attempts: "",
  outbox_batch_size: "",
};

function configToDraft(cfg: EmailConfig): Draft {
  return {
    enabled: cfg.enabled !== undefined ? String(cfg.enabled) : "",
    provider: cfg.provider ?? "",
    from_address: cfg.from_address ?? "",
    from_name: cfg.from_name ?? "",
    smtp_host: cfg.smtp_host ?? "",
    smtp_port: cfg.smtp_port !== undefined ? String(cfg.smtp_port) : "",
    smtp_username: cfg.smtp_username ?? "",
    smtp_password: cfg.smtp_password ?? "",
    outbox_max_attempts:
      cfg.outbox_max_attempts !== undefined ? String(cfg.outbox_max_attempts) : "",
    outbox_batch_size: cfg.outbox_batch_size !== undefined ? String(cfg.outbox_batch_size) : "",
  };
}

function draftToPayload(draft: Draft): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (draft.enabled !== "") payload.enabled = draft.enabled === "true";
  if (draft.provider) payload.provider = draft.provider;
  if (draft.from_address) payload.from_address = draft.from_address;
  if (draft.from_name) payload.from_name = draft.from_name;
  if (draft.smtp_host) payload.smtp_host = draft.smtp_host;
  if (draft.smtp_port) payload.smtp_port = parseInt(draft.smtp_port, 10);
  if (draft.smtp_username) payload.smtp_username = draft.smtp_username;
  if (draft.smtp_password && !isMasked(draft.smtp_password))
    payload.smtp_password = draft.smtp_password;
  if (draft.outbox_max_attempts)
    payload.outbox_max_attempts = parseInt(draft.outbox_max_attempts, 10);
  if (draft.outbox_batch_size) payload.outbox_batch_size = parseInt(draft.outbox_batch_size, 10);
  return payload;
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function EmailConfigPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);

  const fetchData = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const res = await fetch("/api/admin/settings/email-config", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(await res.text());
      const json: EmailConfig = await res.json();
      setDraft(configToDraft(json));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [isSignedIn, getToken]);

  useEffect(() => {
    if (!isGuardLoading && isAdmin) fetchData();
  }, [isGuardLoading, isAdmin, fetchData]);

  const set = (key: keyof Draft, val: string) => setDraft((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const token = await getToken();
      const payload = draftToPayload(draft);
      if (Object.keys(payload).length === 0) {
        setSavedAt("No changes");
        return;
      }
      const res = await fetch("/api/admin/settings/email-config", {
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

  const isSmtp = draft.provider === "smtp" || draft.provider === "";

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
            <span className="max-sm:hidden">{saving ? "Saving…" : "Save"}</span>
          </Button>
        </>
      ) : null,
    });
    return () => setHeader(null);
  }, [isAdmin, loading, saving, setHeader]);

  if (isGuardLoading || loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[13px] text-(--t-3)">
        Loading email configuration…
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
      <DashboardPageIntro icon={Mail} title="Email configuration">
        Email provider settings stored here override <code className={CODE}>.env</code>. Leave blank
        to keep current env value.
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

      {/* General */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>General</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="email-enabled" className={FIELD_LABEL}>
              Email Enabled
            </label>
            <NativeSelect
              id="email-enabled"
              variant="auth"
              value={draft.enabled}
              onChange={(e) => set("enabled", e.target.value)}
            >
              <option value="">, env default, </option>
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
            </NativeSelect>
          </div>
          <div>
            <label htmlFor="email-provider" className={FIELD_LABEL}>
              Provider
            </label>
            <NativeSelect
              id="email-provider"
              variant="auth"
              value={draft.provider}
              onChange={(e) => set("provider", e.target.value)}
            >
              <option value="">, env default, </option>
              <option value="smtp">SMTP</option>
            </NativeSelect>
          </div>
          <div>
            <label htmlFor="from-address" className={FIELD_LABEL}>
              From Address
            </label>
            <input
              id="from-address"
              type="email"
              value={draft.from_address}
              placeholder="noreply@example.com"
              className={WINPUT}
              onChange={(e) => set("from_address", e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="from-name" className={FIELD_LABEL}>
              From Name
            </label>
            <input
              id="from-name"
              type="text"
              value={draft.from_name}
              placeholder="My App"
              className={WINPUT}
              onChange={(e) => set("from_name", e.target.value)}
            />
          </div>
        </div>
      </section>

      {/* SMTP */}
      {(isSmtp || draft.provider === "") && (
        <section className={CARD}>
          <h2 className={CARD_TITLE}>SMTP</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="smtp-host" className={FIELD_LABEL}>
                SMTP Host
              </label>
              <input
                id="smtp-host"
                type="text"
                value={draft.smtp_host}
                placeholder="smtp.example.com"
                className={WINPUT}
                onChange={(e) => set("smtp_host", e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="smtp-port" className={FIELD_LABEL}>
                SMTP Port
              </label>
              <input
                id="smtp-port"
                type="number"
                value={draft.smtp_port}
                placeholder="587"
                min={1}
                max={65535}
                className={WINPUT}
                onChange={(e) => set("smtp_port", e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="smtp-username" className={FIELD_LABEL}>
                SMTP Username
              </label>
              <input
                id="smtp-username"
                type="text"
                value={draft.smtp_username}
                placeholder="user@example.com"
                className={WINPUT}
                onChange={(e) => set("smtp_username", e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="smtp-password" className={FIELD_LABEL}>
                SMTP Password
              </label>
              <div className="relative flex items-center">
                <input
                  id="smtp-password"
                  type={showSmtpPassword ? "text" : "password"}
                  value={
                    isMasked(draft.smtp_password) && !showSmtpPassword ? "" : draft.smtp_password
                  }
                  placeholder={
                    isMasked(draft.smtp_password) && !showSmtpPassword
                      ? "••••••••  (set, enter new value to update)"
                      : "Not set"
                  }
                  className={`${WINPUT} pr-10`}
                  onChange={(e) => set("smtp_password", e.target.value)}
                />
                <button
                  type="button"
                  className="absolute right-3 text-(--t-3) hover:text-(--t-1)"
                  onClick={() => setShowSmtpPassword((v) => !v)}
                  tabIndex={-1}
                  aria-label={showSmtpPassword ? "Hide password" : "Show password"}
                >
                  {showSmtpPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              {isMasked(draft.smtp_password) && (
                <p className="mt-1 flex items-center gap-1 text-[12.5px] text-(--good)">
                  <CheckCircle2 size={11} /> Configured in database
                </p>
              )}
            </div>
          </div>
        </section>
      )}

      {/* Outbox tuning */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>Outbox Tuning</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="outbox-max-attempts" className={FIELD_LABEL}>
              Max Send Attempts
            </label>
            <input
              id="outbox-max-attempts"
              type="number"
              value={draft.outbox_max_attempts}
              placeholder="5 (env default)"
              min={1}
              max={20}
              className={WINPUT}
              onChange={(e) => set("outbox_max_attempts", e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="outbox-batch-size" className={FIELD_LABEL}>
              Batch Size
            </label>
            <input
              id="outbox-batch-size"
              type="number"
              value={draft.outbox_batch_size}
              placeholder="25 (env default)"
              min={1}
              max={500}
              className={WINPUT}
              onChange={(e) => set("outbox_batch_size", e.target.value)}
            />
          </div>
        </div>
      </section>

      <p className="text-right font-(family-name:--mono) text-[11.5px] text-(--t-3)">
        Resolution: DB override → .env / AWS SSM → Settings default
      </p>
    </>
  );
}
