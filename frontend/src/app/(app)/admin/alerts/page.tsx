"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Bell, CheckCircle, AlertTriangle, Activity, MessageSquare } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminTableSkeleton, AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import SignalTabs, { type SignalTab } from "@/components/signal/SignalTabs";
import { toast } from "sonner";

/* ── Types ──────────────────────────────────────────────────────── */

type AlertEvent = {
  id: number;
  rule_id: number;
  rule_name: string;
  metric_key: string;
  current_value: number;
  status: "active" | "acknowledged" | "resolved";
  triggered_at: string;
  resolved_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  notes: string | null;
};

type AlertRule = {
  id: number;
  name: string;
  description: string;
  metric_key: string;
  condition: string;
  threshold_value: number;
  severity: string;
  is_active: boolean;
};

type NotificationChannel = {
  id: number;
  name: string;
  channel_type: string;
  is_active: boolean;
};

/* ── Design tokens ──────────────────────────────────────────────── */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSTAT = "rounded-(--r) border border-(--line) bg-(--panel) px-4 py-3";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

const EVENT_CHIP: Record<string, string> = {
  active: `${CHIP} animate-pulse text-(--bad) bg-(--bad-s)`,
  acknowledged: `${CHIP} text-(--warn) bg-(--warn-s)`,
  resolved: `${CHIP} text-(--good) bg-(--good-s)`,
};

/* ── Main page ──────────────────────────────────────────────────── */

export default function AdminAlertsPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isLoading: isGuardLoading } = useAdminAccess();

  const [activeTab, setActiveTab] = useState<"events" | "rules" | "channels">("events");
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("Not authenticated.");
    return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  }, [getToken]);

  const loadData = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();

      // Parallel fetch
      const [eventsRes, rulesRes, channelsRes] = await Promise.all([
        fetch("/api/admin/alerts/events?limit=100", { headers }),
        fetch("/api/admin/alerts/rules", { headers }),
        fetch("/api/admin/alerts/channels", { headers }),
      ]);

      if (!eventsRes.ok || !rulesRes.ok || !channelsRes.ok) {
        throw new Error("Failed to load alerts data.");
      }

      setEvents(await eventsRes.json());
      setRules(await rulesRes.json());
      setChannels(await channelsRes.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load alerts.");
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleAcknowledge = async (eventId: number) => {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/admin/alerts/events/${eventId}/ack`, {
        method: "PATCH",
        headers,
        body: JSON.stringify({ notes: "Acknowledged via dashboard" }),
      });
      if (!res.ok) throw new Error("Failed to acknowledge alert.");
      toast.success("Alert acknowledged");
      loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Acknowledgment failed.");
    }
  };

  if (loading || isGuardLoading) {
    return (
      <>
        <DashboardPageIntro icon={Bell} title="System alerts">
          Monitor system metrics, active alerts, and configure notification rules.
        </DashboardPageIntro>
        <AdminCardSkeleton cards={3} />
        <AdminTableSkeleton rows={10} columns={5} />
      </>
    );
  }

  if (error) {
    return <AdminInlineError message={error} onRetry={loadData} />;
  }

  const activeEventsCount = events.filter((e) => e.status === "active").length;

  const eventColumns: SignalDataTableColumn<AlertEvent>[] = [
    {
      key: "status",
      header: "Status",
      renderCell: (e) => (
        <span className={EVENT_CHIP[e.status] ?? `${CHIP} text-(--t-2) bg-(--line-2)`}>
          {e.status}
        </span>
      ),
    },
    {
      key: "rule",
      header: "Rule / metric",
      renderCell: (e) => (
        <div>
          <p className="font-semibold text-(--t-1)">{e.rule_name}</p>
          <p className="mt-0.5 font-(family-name:--mono) text-[11px] text-(--t-3)">
            {e.metric_key}
          </p>
        </div>
      ),
    },
    {
      key: "triggered",
      header: "Triggered at",
      renderCell: (e) => (
        <span className="text-xs text-(--t-2)">{new Date(e.triggered_at).toLocaleString()}</span>
      ),
    },
    {
      key: "value",
      header: "Value",
      renderCell: (e) => (
        <span className="font-(family-name:--mono) text-xs text-(--t-1)">{e.current_value}</span>
      ),
    },
    {
      key: "action",
      header: "Action",
      align: "right",
      renderCell: (e) => (
        <>
          {e.status === "active" && (
            <button
              onClick={() => handleAcknowledge(e.id)}
              className={`${CHIP} border border-(--purple) text-(--purple) transition-colors hover:bg-(--purple-s)`}
            >
              Ack
            </button>
          )}
          {e.status === "acknowledged" && e.acknowledged_by && (
            <span className="text-[11px] text-(--t-3)" title={`By ${e.acknowledged_by}`}>
              Ack'd
            </span>
          )}
        </>
      ),
    },
  ];

  const ruleColumns: SignalDataTableColumn<AlertRule>[] = [
    {
      key: "name",
      header: "Rule name",
      renderCell: (r) => <span className="font-semibold text-(--t-1)">{r.name}</span>,
    },
    {
      key: "metric",
      header: "Metric & condition",
      renderCell: (r) => (
        <span className="text-xs">
          <span className="font-(family-name:--mono) text-(--t-2)">{r.metric_key}</span>{" "}
          <span className="text-(--t-3)">{r.condition}</span>{" "}
          <span className="font-(family-name:--mono) text-(--warn)">{r.threshold_value}</span>
        </span>
      ),
    },
    {
      key: "severity",
      header: "Severity",
      renderCell: (r) => (
        <span
          className={`${CHIP} ${r.severity === "critical" ? "text-(--bad) bg-(--bad-s)" : "text-(--warn) bg-(--warn-s)"}`}
        >
          {r.severity}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      renderCell: (r) => (
        <span
          className={
            r.is_active
              ? `${CHIP} text-(--good) bg-(--good-s)`
              : `${CHIP} text-(--t-2) bg-(--line-2)`
          }
        >
          {r.is_active ? "Active" : "Disabled"}
        </span>
      ),
    },
  ];

  const channelColumns: SignalDataTableColumn<NotificationChannel>[] = [
    {
      key: "name",
      header: "Channel name",
      renderCell: (c) => <span className="font-semibold text-(--t-1)">{c.name}</span>,
    },
    {
      key: "type",
      header: "Type",
      renderCell: (c) => <span className={MONO_META}>{c.channel_type}</span>,
    },
    {
      key: "status",
      header: "Status",
      renderCell: (c) => (
        <span
          className={
            c.is_active
              ? `${CHIP} text-(--good) bg-(--good-s)`
              : `${CHIP} text-(--t-2) bg-(--line-2)`
          }
        >
          {c.is_active ? "Active" : "Disabled"}
        </span>
      ),
    },
  ];

  const tabs: SignalTab<"events" | "rules" | "channels">[] = [
    { id: "events", label: "Alert history" },
    { id: "rules", label: "Evaluation rules" },
    { id: "channels", label: "Channels" },
  ];

  return (
    <>
      {/* Header */}
      <DashboardPageIntro icon={Bell} title="System alerts">
        Monitor system metrics, active alerts, and configure notification rules.
      </DashboardPageIntro>

      {/* KPI bar */}
      <div className="grid grid-cols-3 gap-3">
        <div className={`${WSTAT} flex items-center gap-3`}>
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-(--r-md) ${activeEventsCount > 0 ? "bg-(--bad-s) text-(--bad)" : "bg-(--good-s) text-(--good)"}`}
          >
            {activeEventsCount > 0 ? <AlertTriangle size={18} /> : <CheckCircle size={18} />}
          </div>
          <div>
            <p className={MICRO_LABEL}>Active alerts</p>
            <p className="font-(family-name:--disp) text-lg font-bold text-(--t-1)">
              {activeEventsCount}
            </p>
          </div>
        </div>
        <div className={`${WSTAT} flex items-center gap-3`}>
          <div className="flex h-10 w-10 items-center justify-center rounded-(--r-md) bg-(--purple-s) text-(--purple)">
            <Activity size={18} />
          </div>
          <div>
            <p className={MICRO_LABEL}>Configured rules</p>
            <p className="font-(family-name:--disp) text-lg font-bold text-(--t-1)">
              {rules.length}
            </p>
          </div>
        </div>
        <div className={`${WSTAT} flex items-center gap-3`}>
          <div className="flex h-10 w-10 items-center justify-center rounded-(--r-md) bg-(--warn-s) text-(--warn)">
            <MessageSquare size={18} />
          </div>
          <div>
            <p className={MICRO_LABEL}>Notification channels</p>
            <p className="font-(family-name:--disp) text-lg font-bold text-(--t-1)">
              {channels.length}
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <SignalTabs
        tabs={tabs}
        activeId={activeTab}
        onChange={(id) => setActiveTab(id as "events" | "rules" | "channels")}
      />

      {/* Tab content */}
      {activeTab === "events" && (
        <SignalDataTable
          columns={eventColumns}
          rows={events}
          rowKey={(e) => e.id}
          emptyLabel="No events found"
        />
      )}
      {activeTab === "rules" && (
        <SignalDataTable
          columns={ruleColumns}
          rows={rules}
          rowKey={(r) => r.id}
          emptyLabel="No rules configured"
        />
      )}
      {activeTab === "channels" && (
        <SignalDataTable
          columns={channelColumns}
          rows={channels}
          rowKey={(c) => c.id}
          emptyLabel="No channels configured"
        />
      )}
    </>
  );
}
