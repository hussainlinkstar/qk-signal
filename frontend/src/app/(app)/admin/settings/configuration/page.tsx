"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Shield,
  Activity,
  CheckCircle2,
  AlertTriangle,
  RefreshCcw,
  Save,
  Zap,
  HeartPulse,
  Lock,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalMetricStrip from "@/components/signal/SignalMetricStrip";
import { ClientSafeDate } from "@/lib/dateFormat";
import Button from "@/components/ui/Button";
import { Alert, AlertDescription } from "@/components/ui/alert";

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 mb-[14px] flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4";
const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-white px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const WTEXTAREA = `${WINPUT} h-auto min-h-[76px] resize-y py-[11px]`;
const CHIP =
  "inline-flex items-center rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const CHIP_GOOD = `${CHIP} text-(--good) bg-(--good-s)`;
const CHIP_WARN = `${CHIP} text-(--warn) bg-(--warn-s)`;
const CHIP_BAD = `${CHIP} text-(--bad) bg-(--bad-s)`;
const CHIP_NEUTRAL = `${CHIP} text-(--t-2) bg-(--line-2)`;

type IntegrationStatus = {
  key: string;
  name: string;
  status: string;
  note: string;
  admin_note: string;
  action_required: boolean;
  last_checked_at: string | null;
};

type ApiKeyStatus = {
  key: string;
  label: string;
  env_var: string;
  configured: boolean;
  required: boolean;
  status: string;
  source: string;
  last_four: string | null;
  note: string;
  owner: string | null;
  rotation_days: number | null;
  usage: string | null;
  recommended_action: string | null;
  action_required: boolean;
  last_checked_at: string | null;
};

type SecurityCheck = {
  key: string;
  label: string;
  status: string;
  details: string;
  action_required: boolean;
};

type AdminSettingsSummary = {
  total_integrations: number;
  connected_integrations: number;
  degraded_integrations: number;
  missing_integrations: number;
  disabled_integrations: number;
  total_api_keys: number;
  configured_api_keys: number;
  missing_required_api_keys: number;
  placeholder_api_keys: number;
  open_security_issues: number;
  generated_at: string;
};

type AdminSettingsResponse = {
  integrations: IntegrationStatus[];
  api_keys: ApiKeyStatus[];
  security_checks: SecurityCheck[];
  recommendations: string[];
  summary: AdminSettingsSummary;
};

type AdminSettingsPatchRequest = {
  integrations: Array<{ key: string; note: string }>;
  api_keys: Array<{
    key: string;
    note: string;
    owner: string | null;
    rotation_days: number | null;
  }>;
};

export default function ConfigurationPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [settings, setSettings] = useState<AdminSettingsResponse | null>(null);
  const [integrationDrafts, setIntegrationDrafts] = useState<Record<string, string>>({});
  const [apiDrafts, setApiDrafts] = useState<
    Record<
      string,
      {
        note: string;
        owner: string;
        rotation_days: string;
      }
    >
  >({});
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("You must be signed in to access admin settings.");
    return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  }, [getToken]);

  const hydrateDrafts = useCallback((payload: AdminSettingsResponse) => {
    setIntegrationDrafts(
      Object.fromEntries((payload.integrations ?? []).map((i) => [i.key, i.admin_note ?? ""]))
    );
    setApiDrafts(
      Object.fromEntries(
        (payload.api_keys ?? []).map((k) => [
          k.key,
          {
            note: k.note ?? "",
            owner: k.owner ?? "",
            rotation_days: k.rotation_days ? String(k.rotation_days) : "",
          },
        ])
      )
    );
  }, []);

  const loadSettings = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    setSuccessMessage("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/settings", { headers });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Unable to load settings.");
      }
      const payload = (await response.json()) as AdminSettingsResponse;
      setSettings(payload);
      hydrateDrafts(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load settings.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, hydrateDrafts, isSignedIn]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const saveSettings = useCallback(async () => {
    if (!settings) return;
    const payload: AdminSettingsPatchRequest = {
      integrations: (settings.integrations ?? []).map((integration) => ({
        key: integration.key,
        note: (integrationDrafts[integration.key] ?? "").trim(),
      })),
      api_keys: (settings.api_keys ?? []).map((apiKey) => {
        const draft = apiDrafts[apiKey.key];
        const parsed = Number.parseInt(draft?.rotation_days ?? "", 10);
        return {
          key: apiKey.key,
          note: (draft?.note ?? "").trim(),
          owner: (draft?.owner ?? "").trim() || null,
          rotation_days: Number.isFinite(parsed) && parsed >= 7 && parsed <= 3650 ? parsed : null,
        };
      }),
    };

    setIsSaving(true);
    setError("");
    setSuccessMessage("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/settings", {
        method: "PATCH",
        headers,
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Unable to save settings.");
      }
      const result = (await response.json()) as AdminSettingsResponse;
      setSettings(result);
      hydrateDrafts(result);
      setSuccessMessage("Settings saved successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save settings.");
    } finally {
      setIsSaving(false);
    }
  }, [apiDrafts, getAuthHeaders, hydrateDrafts, integrationDrafts, settings]);

  const controlsDisabled = !isAdmin || isGuardLoading || isLoading || isSaving;
  const summary = settings?.summary;

  const openIssueCount = useMemo(() => {
    if (!settings) return 0;
    return (
      settings.integrations.filter((i) => i.action_required).length +
      settings.api_keys.filter((k) => k.action_required).length +
      settings.security_checks.filter((c) => c.action_required).length
    );
  }, [settings]);

  const integrationBadge = (status: string) => {
    const s = status.toLowerCase();
    if (s === "connected") return { cls: CHIP_GOOD, label: "Connected" };
    if (s === "degraded") return { cls: CHIP_WARN, label: "Degraded" };
    if (s === "disabled") return { cls: CHIP_NEUTRAL, label: "Disabled" };
    return { cls: CHIP_BAD, label: "Missing" };
  };

  const apiKeyBadge = (status: string) => {
    if (status === "configured") return { cls: CHIP_GOOD, label: "Configured" };
    if (status === "placeholder") return { cls: CHIP_WARN, label: "Placeholder" };
    return { cls: CHIP_BAD, label: "Missing" };
  };

  const securityBadge = (status: string) => {
    if (status === "pass") return CHIP_GOOD;
    if (status === "warn") return CHIP_WARN;
    return CHIP_BAD;
  };

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void loadSettings()}
            disabled={controlsDisabled}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCcw size={14} className={isLoading ? "animate-spin" : ""} />
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void saveSettings()}
            disabled={controlsDisabled || !settings}
          >
            {isSaving ? <Activity className="animate-pulse" size={14} /> : <Save size={14} />}
            <span className="max-sm:hidden">{isSaving ? "Saving..." : "Save Changes"}</span>
          </Button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [controlsDisabled, isLoading, isSaving, loadSettings, saveSettings, setHeader, settings]);

  return (
    <>
      <DashboardPageIntro icon={Shield} title="Integration &amp; security health">
        Monitor integration connectivity, credential status, and security posture across the
        platform.
      </DashboardPageIntro>

      {/* Inline alerts */}
      {error && (
        <Alert variant="destructive">
          <Shield />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {successMessage && (
        <Alert variant="success">
          <CheckCircle2 />
          <AlertDescription>{successMessage}</AlertDescription>
        </Alert>
      )}

      {/* KPI summary */}
      <SignalMetricStrip
        className="mb-4"
        items={[
          {
            label: "Integrations healthy",
            value: (
              <>
                {summary?.connected_integrations ?? 0}
                <span className="ms-1 text-[13px] font-semibold text-(--t-3)">
                  / {summary?.total_integrations ?? 0}
                </span>
              </>
            ),
          },
          {
            label: "Degraded / missing",
            value:
              (summary?.degraded_integrations ?? 0) + (summary?.missing_integrations ?? 0),
            tone: "warn",
          },
          {
            label: "Credentials ready",
            value: (
              <>
                {summary?.configured_api_keys ?? 0}
                <span className="ms-1 text-[13px] font-semibold text-(--t-3)">
                  / {summary?.total_api_keys ?? 0}
                </span>
              </>
            ),
          },
          {
            label: "Required missing",
            value: summary?.missing_required_api_keys ?? 0,
            tone: "bad",
          },
          {
            label: "Security issues",
            value: summary?.open_security_issues ?? 0,
            tone: "bad",
          },
        ]}
      />

      {/* Recommendations */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>
          <Zap size={15} className="text-(--purple)" /> Recommendations
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(settings?.recommendations ?? []).length ? (
            (settings?.recommendations ?? []).map((rec, idx) => (
              <div key={idx} className={`${INSET} flex items-start gap-3`}>
                <div className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-(--purple)" />
                <p className="text-[12.5px] leading-[1.5] text-(--t-2)">{rec}</p>
              </div>
            ))
          ) : (
            <p className="text-[13px] text-(--t-3)">
              {isLoading ? "Loading..." : "No recommendations at this time."}
            </p>
          )}
        </div>
      </section>

      {/* Integration Diagnostics + Credential Inventory */}
      <div className="grid gap-[22px] xl:grid-cols-2">
        {/* Integration Diagnostics */}
        <section className={`${CARD} flex flex-col`}>
          <h2 className={CARD_TITLE}>
            <HeartPulse size={15} className="text-(--purple)" /> Integration Diagnostics
          </h2>
          <div className="space-y-4">
            {(settings?.integrations ?? []).map((integration) => {
              const { cls, label } = integrationBadge(integration.status);
              return (
                <div
                  key={integration.key}
                  className={`${INSET} transition-colors hover:border-[color-mix(in_srgb,var(--purple)_30%,transparent)]`}
                >
                  <div className="mb-4 flex items-start justify-between gap-4">
                    <div>
                      <h3 className="font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
                        {integration.name}
                      </h3>
                      <p className="mt-1 font-(family-name:--mono) text-[11.5px] text-(--t-3)">
                        {integration.key}
                      </p>
                    </div>
                    <span className={cls}>{label}</span>
                  </div>

                  <p className="mb-4 text-[13px] leading-[1.5] text-(--t-2)">
                    &ldquo;{integration.note}&rdquo;
                  </p>

                  <div className="mb-4">
                    <label htmlFor={`integration-note-${integration.key}`} className={FIELD_LABEL}>
                      Admin Note
                    </label>
                    <textarea
                      id={`integration-note-${integration.key}`}
                      value={integrationDrafts[integration.key] ?? ""}
                      onChange={(e) =>
                        setIntegrationDrafts((prev) => ({
                          ...prev,
                          [integration.key]: e.target.value,
                        }))
                      }
                      disabled={controlsDisabled}
                      rows={2}
                      className={WTEXTAREA}
                      placeholder="Add a note about this integration..."
                    />
                  </div>

                  <div className="flex items-center justify-between border-t border-(--line) pt-4">
                    <div className="flex items-center gap-1.5">
                      <div
                        className={`h-2 w-2 rounded-full ${integration.action_required ? "animate-pulse bg-(--bad)" : "bg-(--good)"}`}
                      />
                      <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                        {integration.action_required ? "Action Required" : "Operational"}
                      </span>
                    </div>
                    <span className="font-(family-name:--mono) text-[11.5px] tabular-nums text-(--t-3)">
                      Checked:{" "}
                      {integration.last_checked_at ? (
                        <ClientSafeDate date={integration.last_checked_at} />
                      ) : (
                        "N/A"
                      )}
                    </span>
                  </div>
                </div>
              );
            })}
            {!isLoading && !settings?.integrations?.length && (
              <p className="py-4 text-center text-[13px] text-(--t-3)">No integrations found.</p>
            )}
          </div>
        </section>

        {/* Credential Inventory */}
        <section className={`${CARD} flex flex-col`}>
          <h2 className={CARD_TITLE}>
            <Lock size={15} className="text-(--purple)" /> Credential Inventory
          </h2>
          <div className="space-y-4">
            {(settings?.api_keys ?? []).map((apiKey) => {
              const { cls, label } = apiKeyBadge(apiKey.status);
              return (
                <div
                  key={apiKey.key}
                  className={`${INSET} transition-colors hover:border-[color-mix(in_srgb,var(--purple)_30%,transparent)]`}
                >
                  <div className="mb-4 flex items-start justify-between gap-4">
                    <div>
                      <h3 className="font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
                        {apiKey.label}
                      </h3>
                      <p className="mt-1 font-(family-name:--mono) text-[11.5px] text-(--t-3)">
                        {apiKey.env_var}
                      </p>
                    </div>
                    <span className={cls}>{label}</span>
                  </div>

                  <div className="mb-4 grid gap-2 sm:grid-cols-2">
                    <div className="flex items-center justify-between rounded-(--r-sm) border-0 bg-white px-3 py-2">
                      <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3)">
                        Required
                      </span>
                      <span className="text-[12.5px] font-medium text-(--t-1)">
                        {apiKey.required ? "Yes" : "No"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between rounded-(--r-sm) border-0 bg-white px-3 py-2">
                      <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3)">
                        Source
                      </span>
                      <span className="text-[12.5px] font-medium text-(--t-1)">
                        {apiKey.source}
                      </span>
                    </div>
                    <div className="flex items-center justify-between rounded-(--r-sm) border-0 bg-white px-3 py-2">
                      <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3)">
                        Last 4
                      </span>
                      <span className="font-(family-name:--mono) text-[11.5px] text-(--t-1)">
                        {apiKey.last_four ? `••••${apiKey.last_four}` : "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between rounded-(--r-sm) border-0 bg-white px-3 py-2">
                      <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3)">
                        Status
                      </span>
                      <span
                        className={`text-[12.5px] font-medium ${apiKey.configured ? "text-(--good)" : "text-(--bad)"}`}
                      >
                        {apiKey.configured ? "Active" : "Not set"}
                      </span>
                    </div>
                  </div>

                  <div className="mb-4 grid gap-3 sm:grid-cols-2">
                    <div>
                      <label htmlFor={`cred-owner-${apiKey.key}`} className={FIELD_LABEL}>
                        Owner
                      </label>
                      <input
                        id={`cred-owner-${apiKey.key}`}
                        value={apiDrafts[apiKey.key]?.owner ?? ""}
                        onChange={(e) =>
                          setApiDrafts((prev) => ({
                            ...prev,
                            [apiKey.key]: {
                              note: prev[apiKey.key]?.note ?? apiKey.note ?? "",
                              owner: e.target.value,
                              rotation_days:
                                prev[apiKey.key]?.rotation_days ??
                                (apiKey.rotation_days ? String(apiKey.rotation_days) : ""),
                            },
                          }))
                        }
                        placeholder="Owner or team"
                        disabled={controlsDisabled}
                        className={WINPUT}
                      />
                    </div>
                    <div>
                      <label htmlFor={`cred-rotation-${apiKey.key}`} className={FIELD_LABEL}>
                        Rotation (Days)
                      </label>
                      <input
                        id={`cred-rotation-${apiKey.key}`}
                        type="number"
                        min={7}
                        max={3650}
                        value={apiDrafts[apiKey.key]?.rotation_days ?? ""}
                        onChange={(e) =>
                          setApiDrafts((prev) => ({
                            ...prev,
                            [apiKey.key]: {
                              note: prev[apiKey.key]?.note ?? apiKey.note ?? "",
                              owner: prev[apiKey.key]?.owner ?? apiKey.owner ?? "",
                              rotation_days: e.target.value,
                            },
                          }))
                        }
                        placeholder="e.g. 90"
                        disabled={controlsDisabled}
                        className={WINPUT}
                      />
                    </div>
                  </div>

                  <div className="mb-2">
                    <textarea
                      id={`cred-note-${apiKey.key}`}
                      aria-label="Notes"
                      value={apiDrafts[apiKey.key]?.note ?? ""}
                      onChange={(e) =>
                        setApiDrafts((prev) => ({
                          ...prev,
                          [apiKey.key]: {
                            note: e.target.value,
                            owner: prev[apiKey.key]?.owner ?? apiKey.owner ?? "",
                            rotation_days:
                              prev[apiKey.key]?.rotation_days ??
                              (apiKey.rotation_days ? String(apiKey.rotation_days) : ""),
                          },
                        }))
                      }
                      disabled={controlsDisabled}
                      rows={2}
                      className={WTEXTAREA}
                      placeholder="Notes, rotation policy, or incident context"
                    />
                  </div>

                  {apiKey.action_required && (
                    <div className="flex items-center gap-2 rounded-(--r-sm) border-0 bg-(--bad-s) px-3 py-2">
                      <AlertTriangle size={12} className="text-(--bad)" />
                      <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--bad)">
                        Action Required
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
            {!isLoading && !settings?.api_keys?.length && (
              <p className="py-4 text-center text-[13px] text-(--t-3)">No credentials found.</p>
            )}
          </div>
        </section>
      </div>

      {/* Security Posture */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>
          <Shield size={15} className="text-(--purple)" /> Security Posture
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {(settings?.security_checks ?? []).map((check) => (
            <div key={check.key} className={INSET}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-[13.5px] font-bold text-(--t-1)">{check.label}</p>
                <span className={securityBadge(check.status)}>
                  {check.status === "pass" ? "OK" : check.status === "warn" ? "Warning" : "Failed"}
                </span>
              </div>
              <p className="text-[12.5px] leading-[1.5] text-(--t-3)">{check.details}</p>
            </div>
          ))}
          {!isLoading && !settings?.security_checks?.length && (
            <p className="col-span-2 py-4 text-center text-[13px] text-(--t-3)">
              No security checks available.
            </p>
          )}
        </div>
      </section>

      {/* Save bar */}
      <section className={`${CARD} flex flex-wrap items-center justify-between gap-6`}>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-1)">
              Status
            </span>
            <div className="h-1.5 w-1.5 rounded-full bg-(--good)" />
          </div>
          <div className="flex items-center gap-4 font-(family-name:--mono) text-[11.5px] text-(--t-3)">
            <span>
              Open Issues: <span className="text-(--purple)">{openIssueCount}</span>
            </span>
            <span>
              Last Refreshed:{" "}
              {summary?.generated_at ? <ClientSafeDate date={summary.generated_at} /> : "N/A"}
            </span>
          </div>
        </div>
      </section>
    </>
  );
}
