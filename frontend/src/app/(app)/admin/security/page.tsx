"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ShieldCheck, ShieldAlert, UserX, Laptop } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import SignalTabs from "@/components/signal/SignalTabs";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminTableSkeleton, AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import { toast } from "sonner";

/* ── Types ──────────────────────────────────────────────────────── */

type SecurityEvent = {
  id: number;
  event_type: string;
  user_id: number | null;
  ip_address: string | null;
  user_agent: string | null;
  severity: string;
  metadata_json: any;
  created_at: string;
};

type UserSession = {
  id: number;
  user_id: number;
  token_jti: string;
  ip_address: string | null;
  user_agent: string | null;
  device_name: string | null;
  is_active: boolean;
  last_activity_at: string | null;
  expires_at: string;
  created_at: string;
};

const STAT = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const CHIP =
  "inline-flex items-center rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

const severityChipClass = (severity: string) => {
  if (severity === "critical" || severity === "error") return `${CHIP} text-(--bad) bg-(--bad-s)`;
  if (severity === "warning") return `${CHIP} text-(--warn) bg-(--warn-s)`;
  return `${CHIP} text-(--good) bg-(--good-s)`;
};

/* ── Main page ──────────────────────────────────────────────────── */

export default function AdminSecurityPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isLoading: isGuardLoading } = useAdminAccess();

  const [activeTab, setActiveTab] = useState<"events" | "sessions">("events");
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [sessions, setSessions] = useState<UserSession[]>([]);
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
      const [eventsRes, sessionsRes] = await Promise.all([
        fetch("/api/admin/security/events?limit=100", { headers }),
        fetch("/api/admin/security/sessions?limit=100", { headers }),
      ]);

      if (!eventsRes.ok || !sessionsRes.ok) {
        throw new Error("Failed to load security data.");
      }

      const eventsData = await eventsRes.json();
      const sessionsData = await sessionsRes.json();

      setEvents(eventsData.items || []);
      setSessions(sessionsData.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load security dashboard.");
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRevokeSession = async (sessionId: number) => {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/admin/security/sessions/${sessionId}/revoke`, {
        method: "POST",
        headers,
      });
      if (!res.ok) throw new Error("Failed to revoke session.");
      toast.success("Session revoked successfully");
      loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Revocation failed.");
    }
  };

  const handleRevokeAllUserSessions = async (userId: number) => {
    if (!confirm(`Are you sure you want to revoke all active sessions for User ID ${userId}?`))
      return;
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/admin/security/users/${userId}/logout-all`, {
        method: "POST",
        headers,
      });
      if (!res.ok) throw new Error("Failed to revoke user sessions.");
      toast.success(`Revoked all sessions for user ${userId}`);
      loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Revocation failed.");
    }
  };

  const eventColumns: SignalDataTableColumn<SecurityEvent>[] = [
    {
      key: "severity",
      header: "Severity",
      sortable: true,
      sortValue: (e) => e.severity,
      renderCell: (e) => <span className={severityChipClass(e.severity)}>{e.severity}</span>,
    },
    {
      key: "event_type",
      header: "Event type",
      sortable: true,
      sortValue: (e) => e.event_type,
      renderCell: (e) => <span className="font-semibold">{e.event_type}</span>,
    },
    {
      key: "user",
      header: "User ID",
      renderCell: (e) => (
        <span className="font-(family-name:--mono) text-xs text-(--t-2)">
          {e.user_id ? `User ${e.user_id}` : "Anonymous"}
        </span>
      ),
    },
    {
      key: "network",
      header: "Network / Device",
      renderCell: (e) => (
        <>
          <div className="font-(family-name:--mono) text-[11px] text-(--t-2)">
            {e.ip_address || "Unknown IP"}
          </div>
          <div
            className="max-w-[200px] truncate text-[11px] text-(--t-3)"
            title={e.user_agent || ""}
          >
            {e.user_agent || "Unknown UA"}
          </div>
        </>
      ),
    },
    {
      key: "created_at",
      header: "Timestamp",
      sortable: true,
      sortValue: (e) => e.created_at,
      renderCell: (e) => (
        <span className="text-(--t-2)">{new Date(e.created_at).toLocaleString()}</span>
      ),
    },
  ];

  const sessionColumns: SignalDataTableColumn<UserSession>[] = [
    {
      key: "user",
      header: "User ID",
      sortable: true,
      sortValue: (s) => s.user_id,
      renderCell: (s) => (
        <>
          <p className="font-semibold">User {s.user_id}</p>
          <p
            className="mt-0.5 max-w-[100px] truncate font-(family-name:--mono) text-[11px] text-(--t-3)"
            title={s.token_jti}
          >
            {s.token_jti}
          </p>
        </>
      ),
    },
    {
      key: "device",
      header: "Device / IP",
      renderCell: (s) => (
        <>
          <span className="font-(family-name:--mono) text-(--t-2)">{s.ip_address}</span>
          <div className="mt-0.5 text-[11px] text-(--t-3)">
            {s.device_name || s.user_agent?.substring(0, 30) || "Unknown Device"}
          </div>
        </>
      ),
    },
    {
      key: "created_at",
      header: "Created at",
      sortable: true,
      sortValue: (s) => s.created_at,
      renderCell: (s) => (
        <span className="text-(--t-2)">{new Date(s.created_at).toLocaleString()}</span>
      ),
    },
    {
      key: "expires_at",
      header: "Expires at",
      sortable: true,
      sortValue: (s) => s.expires_at,
      renderCell: (s) => (
        <span className="text-(--t-2)">{new Date(s.expires_at).toLocaleString()}</span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      renderCell: (s) => (
        <div className="flex gap-2">
          <button
            onClick={() => handleRevokeSession(s.id)}
            className="rounded-md border border-(--line) bg-(--bad-s) px-2.5 py-1 font-(family-name:--mono) text-[10.5px] tracking-[0.04em] text-(--bad) transition-colors hover:opacity-80"
          >
            Revoke
          </button>
          <button
            onClick={() => handleRevokeAllUserSessions(s.user_id)}
            className="rounded-md border border-(--line) bg-(--warn-s) px-2.5 py-1 text-(--warn) transition-colors hover:opacity-80"
            title="Revoke all sessions for this user"
          >
            <UserX size={12} />
          </button>
        </div>
      ),
    },
  ];

  if (loading || isGuardLoading) {
    return (
      <>
        <DashboardPageIntro icon={ShieldCheck} title="Security logs and sessions" />
        <AdminCardSkeleton cards={2} />
        <AdminTableSkeleton rows={10} columns={5} />
      </>
    );
  }

  if (error) {
    return <AdminInlineError message={error} onRetry={loadData} />;
  }

  const warningEvents = events.filter(
    (e) => e.severity === "warning" || e.severity === "critical"
  ).length;

  return (
    <>
      <DashboardPageIntro icon={ShieldCheck} title="Security logs and sessions">
        Monitor recent security events and manage active user sessions across the platform.
      </DashboardPageIntro>

      {/* KPI bar */}
      <div className="grid grid-cols-2 gap-4">
        <div className={STAT}>
          <div className="flex items-center justify-between">
            <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
              {warningEvents}
            </p>
            {warningEvents > 0 ? (
              <ShieldAlert size={16} className="text-(--warn)" />
            ) : (
              <ShieldCheck size={16} className="text-(--good)" />
            )}
          </div>
          <p className={`${MICRO_LABEL} mt-1`}>Warning events</p>
        </div>
        <div className={STAT}>
          <div className="flex items-center justify-between">
            <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
              {sessions.length}
            </p>
            <Laptop size={16} className="text-(--purple)" />
          </div>
          <p className={`${MICRO_LABEL} mt-1`}>Active sessions</p>
        </div>
      </div>

      <SignalTabs
        tabs={[
          { id: "events", label: "Security events" },
          { id: "sessions", label: "Active sessions" },
        ]}
        activeId={activeTab}
        onChange={(id) => setActiveTab(id as "events" | "sessions")}
      />

      {activeTab === "events" ? (
        <SignalDataTable
          columns={eventColumns}
          rows={events}
          rowKey={(e) => e.id}
          emptyLabel="No security events found"
          searchPlaceholder="Search events"
          searchText={(e) =>
            `${e.event_type} ${e.severity} ${e.user_id ?? ""} ${e.ip_address ?? ""} ${e.user_agent ?? ""}`
          }
          pageSize={25}
          metaLabel={`${events.length} events`}
        />
      ) : (
        <SignalDataTable
          columns={sessionColumns}
          rows={sessions}
          rowKey={(s) => s.id}
          emptyLabel="No active sessions found"
          searchPlaceholder="Search sessions"
          searchText={(s) =>
            `${s.user_id} ${s.ip_address ?? ""} ${s.user_agent ?? ""} ${s.device_name ?? ""} ${s.token_jti}`
          }
          pageSize={25}
          metaLabel={`${sessions.length} sessions`}
        />
      )}
    </>
  );
}
