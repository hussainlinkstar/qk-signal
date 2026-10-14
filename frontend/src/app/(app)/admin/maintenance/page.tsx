"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  ToggleLeft,
  AlertTriangle,
  Zap,
  FileText,
  Mail,
  CreditCard,
  Users,
  Lock,
  Calendar,
  BarChart3,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import Button from "@/components/ui/Button";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import { toast } from "sonner";

/* ── Types ──────────────────────────────────────────────────────── */

type MaintenanceState = {
  enabled: boolean;
  message: string;
  allowed_emails: string[];
  scheduled_start?: string | null;
  scheduled_end?: string | null;
};

type FeatureSwitches = Record<string, boolean>;

const CARD = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border border-(--line) bg-(--paper) px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const WTEXTAREA = `${WINPUT} h-auto min-h-[76px] resize-y py-[11px]`;
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const TOGGLE_ROW =
  "flex items-center justify-between gap-4 border-t border-(--line-2) py-3.5 first:border-t-0";

/* ── Feature switch metadata ─────────────────────────────────────── */

const FEATURE_META: Record<
  string,
  { label: string; description: string; icon: React.ReactNode; color: string }
> = {
  audits_enabled: {
    label: "Assessments",
    description: "Run new assessment reports",
    icon: <Zap size={16} />,
    color: "text-(--purple)",
  },
  pdf_generation_enabled: {
    label: "PDF Generation",
    description: "Generate audit PDF exports",
    icon: <FileText size={16} />,
    color: "text-(--purple)",
  },
  email_sending_enabled: {
    label: "Email Sending",
    description: "Outbound email delivery",
    icon: <Mail size={16} />,
    color: "text-(--good)",
  },
  billing_enabled: {
    label: "Billing",
    description: "Stripe payment processing",
    icon: <CreditCard size={16} />,
    color: "text-(--warn)",
  },
  cms_generation_enabled: {
    label: "CMS Generation",
    description: "AI article & case study generation",
    icon: <FileText size={16} />,
    color: "text-(--purple)",
  },
  signups_enabled: {
    label: "Signups",
    description: "New user registration",
    icon: <Users size={16} />,
    color: "text-(--bad)",
  },
  oauth_enabled: {
    label: "OAuth / SSO",
    description: "Google, GitHub, LinkedIn login",
    icon: <Lock size={16} />,
    color: "text-(--purple)",
  },
  scheduled_audits_enabled: {
    label: "Scheduled Assessments",
    description: "Automated recurring audits",
    icon: <Calendar size={16} />,
    color: "text-(--good)",
  },
  competitor_analysis_enabled: {
    label: "Competitor Analysis",
    description: "Competitor tracking & analysis",
    icon: <BarChart3 size={16} />,
    color: "text-(--warn)",
  },
};

/* ── Main page ──────────────────────────────────────────────────── */

export default function AdminMaintenancePage() {
  const { getToken, isSignedIn } = useAuth();
  const { isLoading: isGuardLoading } = useAdminAccess();

  const [maintenance, setMaintenance] = useState<MaintenanceState>({
    enabled: false,
    message: "",
    allowed_emails: [],
  });
  const [switches, setSwitches] = useState<FeatureSwitches>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // Toggle confirmation
  const [confirmToggle, setConfirmToggle] = useState(false);
  const [draftMessage, setDraftMessage] = useState("");
  const [draftEmails, setDraftEmails] = useState("");

  // Scheduling
  const [scheduleStart, setScheduleStart] = useState("");
  const [scheduleEnd, setScheduleEnd] = useState("");
  const [scheduling, setScheduling] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("Not authenticated.");
    return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  }, [getToken]);

  const loadState = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const res = await fetch("/api/admin/maintenance", { headers });
      if (!res.ok) throw new Error("Failed to load maintenance status.");
      const data = await res.json();
      setMaintenance(data.maintenance);
      setSwitches(data.feature_switches);
      setDraftMessage(data.maintenance.message || "");
      setDraftEmails((data.maintenance.allowed_emails || []).join(", "));

      if (data.maintenance.scheduled_start) {
        // Convert ISO to local datetime string for input type="datetime-local"
        const sd = new Date(data.maintenance.scheduled_start);
        sd.setMinutes(sd.getMinutes() - sd.getTimezoneOffset());
        setScheduleStart(sd.toISOString().slice(0, 16));
      } else {
        setScheduleStart("");
      }
      if (data.maintenance.scheduled_end) {
        const ed = new Date(data.maintenance.scheduled_end);
        ed.setMinutes(ed.getMinutes() - ed.getTimezoneOffset());
        setScheduleEnd(ed.toISOString().slice(0, 16));
      } else {
        setScheduleEnd("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load maintenance status.");
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadState();
  }, [loadState]);

  const toggleMaintenance = useCallback(async () => {
    setSaving(true);
    try {
      const headers = await getAuthHeaders();
      const newEnabled = !maintenance.enabled;
      const res = await fetch("/api/admin/maintenance/toggle", {
        method: "POST",
        headers,
        body: JSON.stringify({
          enabled: newEnabled,
          message: draftMessage.trim(),
          allowed_emails: draftEmails
            .split(",")
            .map((e) => e.trim())
            .filter(Boolean),
        }),
      });
      if (!res.ok) throw new Error("Failed to toggle maintenance mode.");
      toast.success(newEnabled ? "Maintenance mode ENABLED" : "Maintenance mode DISABLED");
      setConfirmToggle(false);
      loadState();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Toggle failed.");
    } finally {
      setSaving(false);
    }
  }, [getAuthHeaders, maintenance.enabled, draftMessage, draftEmails, loadState]);

  const toggleFeature = useCallback(
    async (key: string) => {
      try {
        const headers = await getAuthHeaders();
        const res = await fetch("/api/admin/feature-switches", {
          method: "PATCH",
          headers,
          body: JSON.stringify({ switches: { [key]: !switches[key] } }),
        });
        if (!res.ok) throw new Error("Failed to update feature switch.");
        const data = await res.json();
        setSwitches(data.feature_switches);
        toast.success(
          `${FEATURE_META[key]?.label || key} ${!switches[key] ? "enabled" : "disabled"}`
        );
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Update failed.");
      }
    },
    [getAuthHeaders, switches]
  );

  const saveSchedule = useCallback(async () => {
    setScheduling(true);
    try {
      const headers = await getAuthHeaders();
      const startObj = scheduleStart ? new Date(scheduleStart) : null;
      const endObj = scheduleEnd ? new Date(scheduleEnd) : null;

      const res = await fetch("/api/admin/maintenance/schedule", {
        method: "POST",
        headers,
        body: JSON.stringify({
          scheduled_start: startObj ? startObj.toISOString() : null,
          scheduled_end: endObj ? endObj.toISOString() : null,
          message: draftMessage.trim(),
          allowed_ips: draftEmails
            .split(",")
            .map((e) => e.trim())
            .filter(Boolean),
        }),
      });
      if (!res.ok) throw new Error("Failed to save schedule.");
      toast.success("Maintenance schedule updated");
      loadState();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Schedule update failed.");
    } finally {
      setScheduling(false);
    }
  }, [getAuthHeaders, scheduleStart, scheduleEnd, draftMessage, draftEmails, loadState]);

  if (loading || isGuardLoading) {
    return (
      <>
        <DashboardPageIntro icon={ToggleLeft} title="Maintenance mode" />
        <AdminCardSkeleton cards={2} />
      </>
    );
  }

  if (error) {
    return <AdminInlineError message={error} onRetry={loadState} />;
  }

  const disabledCount = Object.values(switches).filter((v) => !v).length;

  return (
    <>
      <DashboardPageIntro icon={ToggleLeft} title="Maintenance mode">
        Toggle maintenance mode and control individual feature availability.
      </DashboardPageIntro>

      {/* Maintenance toggle */}
      <section className={CARD}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className={CARD_TITLE}>Global maintenance mode</h2>
            <div className="mt-2 flex items-center gap-3">
              <span
                className={`${CHIP} ${
                  maintenance.enabled ? "text-(--bad) bg-(--bad-s)" : "text-(--good) bg-(--good-s)"
                }`}
              >
                {maintenance.enabled ? <XCircle size={12} /> : <CheckCircle size={12} />}
                {maintenance.enabled
                  ? "ACTIVE, Platform is offline"
                  : "INACTIVE, Platform running normally"}
              </span>
            </div>
          </div>
          <Button
            variant={maintenance.enabled ? "primary" : "danger"}
            onClick={() => setConfirmToggle(true)}
          >
            {maintenance.enabled ? "Disable Maintenance" : "Enable Maintenance"}
          </Button>
        </div>

        {/* Draft fields */}
        <div className="mt-6 space-y-4">
          <div>
            <label className={FIELD_LABEL}>Maintenance Message</label>
            <textarea
              value={draftMessage}
              onChange={(e) => setDraftMessage(e.target.value)}
              placeholder="We are performing scheduled maintenance. Service will resume shortly."
              rows={2}
              className={`${WTEXTAREA} resize-none`}
            />
          </div>
          <div>
            <label className={FIELD_LABEL}>Allowed Emails (bypass, comma-separated)</label>
            <input
              type="text"
              value={draftEmails}
              onChange={(e) => setDraftEmails(e.target.value)}
              placeholder="admin@example.com, dev@example.com"
              className={WINPUT}
            />
          </div>
        </div>

        {/* Confirmation */}
        {confirmToggle && (
          <Alert variant="warning" className="mt-4">
            <AlertTriangle />
            <AlertDescription>
              <p className="font-semibold">
                {maintenance.enabled
                  ? "Are you sure you want to disable maintenance mode?"
                  : "Are you sure you want to enable maintenance mode? Existing users will be affected."}
              </p>
              <div className="mt-3 flex gap-2">
                <Button
                  variant={maintenance.enabled ? "primary" : "danger"}
                  size="sm"
                  onClick={toggleMaintenance}
                  disabled={saving}
                >
                  {saving ? "Saving..." : "Confirm"}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmToggle(false)}>
                  Cancel
                </Button>
              </div>
            </AlertDescription>
          </Alert>
        )}
      </section>

      {/* Schedule config */}
      <section className={CARD}>
        <h2 className={CARD_TITLE}>Schedule maintenance window</h2>
        <p className="mt-2 text-[13px] leading-[1.5] text-(--t-2)">
          Set a future timeframe. During this window, maintenance mode will be automatically
          enforced, and the yellow warning banner will appear 24h prior.
        </p>

        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className={FIELD_LABEL}>Start Time (Local)</label>
            <input
              type="datetime-local"
              value={scheduleStart}
              onChange={(e) => setScheduleStart(e.target.value)}
              className={WINPUT}
            />
          </div>
          <div>
            <label className={FIELD_LABEL}>End Time (Local)</label>
            <input
              type="datetime-local"
              value={scheduleEnd}
              onChange={(e) => setScheduleEnd(e.target.value)}
              className={WINPUT}
            />
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-3">
          <Button
            variant="ghost"
            onClick={() => {
              setScheduleStart("");
              setScheduleEnd("");
            }}
          >
            Clear
          </Button>
          <Button variant="primary" onClick={saveSchedule} disabled={scheduling}>
            {scheduling ? "Saving..." : "Save Schedule"}
          </Button>
        </div>
      </section>

      {/* Feature kill switches */}
      <section className={CARD}>
        <div className="flex items-center justify-between">
          <h2 className={CARD_TITLE}>Feature kill switches</h2>
          {disabledCount > 0 && (
            <span className={`${CHIP} text-(--warn) bg-(--warn-s)`}>
              {disabledCount} feature{disabledCount > 1 ? "s" : ""} disabled
            </span>
          )}
        </div>
        <div className="mt-2">
          {Object.entries(switches).map(([key, enabled]) => {
            const meta = FEATURE_META[key] || {
              label: key,
              description: "",
              icon: <Zap size={16} />,
              color: "text-(--t-2)",
            };
            return (
              <div key={key} className={TOGGLE_ROW}>
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-(--r-md) bg-(--paper) ${meta.color}`}
                  >
                    {meta.icon}
                  </div>
                  <div>
                    <p className="text-[13.5px] font-semibold text-(--t-1)">{meta.label}</p>
                    {meta.description && (
                      <p className="mt-0.5 max-w-[560px] text-xs text-(--t-3)">
                        {meta.description}
                      </p>
                    )}
                  </div>
                </div>
                <ToggleSwitch
                  checked={enabled}
                  onChange={() => toggleFeature(key)}
                  aria-label={meta.label}
                />
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}
