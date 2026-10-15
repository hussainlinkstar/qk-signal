"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  FileText,
  Loader2,
  Search,
  Shield,
  ShieldOff,
  Trash2,
  UserX,
  X,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import SignalTabs from "@/components/signal/SignalTabs";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useDebounce } from "@/hooks/useDebounce";

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type GdprUserRow = {
  user_id: number;
  email: string;
  role: string;
  company_name: string | null;
  audit_count: number;
  anonymized_at: string | null;
};

type GdprUserSummary = {
  user_id: number;
  email: string;
  role: string;
  company_name: string | null;
  created_at: string | null;
  anonymized_at: string | null;
  audit_count: number;
  email_count: number;
  payment_count: number;
  has_subscription: boolean;
};

type DataMapEntry = {
  category: string;
  table: string;
  pii_fields: string[];
  retention_policy: string;
  legal_basis: string;
  record_count: number;
};

type DataMapResponse = {
  entries: DataMapEntry[];
  total_users: number;
  anonymized_users: number;
};

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const STAT = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const TH =
  "border-b border-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)";
const TD = "border-b border-(--line-2) px-4 py-[11px] align-middle text-[13px] text-(--t-1)";
const TROW = "transition-colors hover:bg-(--paper)";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const CHIP_BAD = `${CHIP} text-(--bad) bg-(--bad-s)`;
const CHIP_GOOD = `${CHIP} text-(--good) bg-(--good-s)`;
const CHIP_WARN = `${CHIP} text-(--warn) bg-(--warn-s)`;
const CHIP_NEUTRAL = `${CHIP} text-(--t-2) bg-(--line-2)`;

/* -------------------------------------------------------------------------- */
/*  Component                                                                  */
/* -------------------------------------------------------------------------- */

export default function AdminGdprPage() {
  useAdminAccess();
  const { getToken } = useAuth();

  /* ---- State ---- */
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedQuery = useDebounce(searchQuery, 400);
  const [users, setUsers] = useState<GdprUserRow[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersPage, setUsersPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const [dataMap, setDataMap] = useState<DataMapResponse | null>(null);

  const [selectedUser, setSelectedUser] = useState<GdprUserSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [exportData, setExportData] = useState<object | null>(null);
  const [exporting, setExporting] = useState(false);

  const [anonymizeEmail, setAnonymizeEmail] = useState("");
  const [anonymizing, setAnonymizing] = useState(false);

  const [tab, setTab] = useState<"users" | "datamap">("users");

  const headers = useCallback(async () => {
    const token = await getToken();
    return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  }, [getToken]);

  /* ---- Fetchers ---- */

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const h = await headers();
      const params = new URLSearchParams({ page: String(usersPage), page_size: "20" });
      if (debouncedQuery) params.set("q", debouncedQuery);
      const res = await fetch(`/api/admin/gdpr/user/search?${params}`, { headers: h });
      if (res.ok) {
        const data = await res.json();
        setUsers(data.items || []);
        setUsersTotal(data.total || 0);
      }
    } catch {
      /* ignore */
    }
    setLoading(false);
  }, [headers, usersPage, debouncedQuery]);

  const fetchDataMap = useCallback(async () => {
    try {
      const h = await headers();
      const res = await fetch("/api/admin/gdpr/data-map", { headers: h });
      if (res.ok) setDataMap(await res.json());
    } catch {
      /* ignore */
    }
  }, [headers]);

  const fetchUserDetail = useCallback(
    async (userId: number) => {
      setDetailLoading(true);
      try {
        const h = await headers();
        const res = await fetch(`/api/admin/gdpr/user/${userId}`, { headers: h });
        if (res.ok) setSelectedUser(await res.json());
      } catch {
        /* ignore */
      }
      setDetailLoading(false);
    },
    [headers]
  );

  /* ---- Effects ---- */
  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);
  useEffect(() => {
    fetchDataMap();
  }, [fetchDataMap]);

  /* ---- Actions ---- */

  const handleExport = useCallback(
    async (userId: number) => {
      setExporting(true);
      try {
        const h = await headers();
        const res = await fetch(`/api/admin/gdpr/export/${userId}`, {
          method: "POST",
          headers: h,
        });
        if (res.ok) {
          const data = await res.json();
          setExportData(data);
        } else {
          const err = await res.json().catch(() => null);
          alert(err?.detail || "Export failed");
        }
      } catch {
        alert("Network error");
      }
      setExporting(false);
    },
    [headers]
  );

  const handleDownloadExport = useCallback(() => {
    if (!exportData) return;
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gdpr_export_${selectedUser?.user_id || "unknown"}_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [exportData, selectedUser]);

  const handleAnonymize = useCallback(
    async (userId: number) => {
      setAnonymizing(true);
      try {
        const h = await headers();
        const res = await fetch(`/api/admin/gdpr/anonymize/${userId}`, {
          method: "POST",
          headers: h,
          body: JSON.stringify({ confirm_email: anonymizeEmail }),
        });
        const data = await res.json();
        if (res.ok) {
          alert(data.message || "User anonymized successfully");
          setSelectedUser(null);
          setAnonymizeEmail("");
          fetchUsers();
        } else {
          alert(data.detail || "Anonymization failed");
        }
      } catch {
        alert("Network error");
      }
      setAnonymizing(false);
    },
    [headers, anonymizeEmail, fetchUsers]
  );

  /* ---- Derived ---- */
  const totalPages = Math.ceil(usersTotal / 20) || 1;

  const closeDetail = () => {
    setSelectedUser(null);
    setExportData(null);
    setAnonymizeEmail("");
  };

  const userColumns: SignalDataTableColumn<GdprUserRow>[] = [
    {
      key: "id",
      header: "ID",
      renderCell: (u) => (
        <span className="font-(family-name:--mono) text-(--t-2)">{u.user_id}</span>
      ),
    },
    { key: "email", header: "Email", renderCell: (u) => u.email },
    {
      key: "company",
      header: "Company",
      renderCell: (u) => <span className="text-(--t-2)">{u.company_name || "-"}</span>,
    },
    {
      key: "role",
      header: "Role",
      renderCell: (u) => (
        <span className={u.role === "admin" ? CHIP_BAD : CHIP_NEUTRAL}>{u.role}</span>
      ),
    },
    {
      key: "audits",
      header: "Audits",
      align: "right",
      renderCell: (u) => (
        <span className="font-(family-name:--mono) text-(--t-2)">{u.audit_count}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      renderCell: (u) =>
        u.anonymized_at ? (
          <span className={CHIP_WARN}>
            <UserX size={10} /> Anonymized
          </span>
        ) : (
          <span className={CHIP_GOOD}>Active</span>
        ),
    },
    {
      key: "actions",
      header: "Actions",
      renderCell: (u) => (
        <div className="flex items-center gap-1">
          <button
            onClick={() => fetchUserDetail(u.user_id)}
            className="rounded-(--r-sm) p-1.5 text-(--t-2) transition-colors hover:bg-(--line-2) hover:text-(--t-1)"
            title="View details"
          >
            <Eye size={14} />
          </button>
          <button
            onClick={() => {
              fetchUserDetail(u.user_id);
              handleExport(u.user_id);
            }}
            className="rounded-(--r-sm) p-1.5 text-(--purple) transition-colors hover:bg-(--line-2)"
            title="Export SAR data"
          >
            <Download size={14} />
          </button>
        </div>
      ),
    },
  ];

  return (
    <>
      <DashboardPageIntro icon={Shield} title="Data privacy (GDPR)">
        Subject access requests, anonymization, and data processing register
      </DashboardPageIntro>

      <SignalTabs
        tabs={[
          { id: "users", label: "User lookup" },
          { id: "datamap", label: "Data processing register" },
        ]}
        activeId={tab}
        onChange={(id) => setTab(id as "users" | "datamap")}
      />

      {/* ---- Tab: Users ---- */}
      {tab === "users" && (
        <>
          {/* Summary stats */}
          {dataMap && (
            <div className="grid grid-cols-3 gap-4">
              <div className={STAT}>
                <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
                  {dataMap.total_users}
                </p>
                <p className={`${MICRO_LABEL} mt-1`}>Total users</p>
              </div>
              <div className={STAT}>
                <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--warn)">
                  {dataMap.anonymized_users}
                </p>
                <p className={`${MICRO_LABEL} mt-1`}>Anonymized</p>
              </div>
              <div className={STAT}>
                <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--good)">
                  {dataMap.total_users - dataMap.anonymized_users}
                </p>
                <p className={`${MICRO_LABEL} mt-1`}>Active</p>
              </div>
            </div>
          )}

          <SignalDataTable
            columns={userColumns}
            rows={users}
            rowKey={(u) => u.user_id}
            emptyLabel={loading ? "Loading..." : "No users found."}
            tools={
              <div className="relative max-w-[250px] flex-1">
                <Search
                  size={14}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-(--t-3)"
                />
                <input
                  type="text"
                  placeholder="Search by email or company name…"
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setUsersPage(1);
                  }}
                  aria-label="Search by email or company name"
                  className="field-focus-ring h-8 w-full rounded-(--r-sm) border-0 bg-[#EEF1F6] pl-8 pr-7 text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c9cef7]"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-(--t-3) hover:text-(--t-1)"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
            }
            metaLabel={`${usersTotal} users`}
            pageSize={20}
            footer={
              usersTotal > 20 ? (
                <>
                  <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
                    {usersTotal} total · Page {usersPage} of {totalPages}
                  </span>
                  <nav className="ms-auto inline-flex items-center gap-1" aria-label="Pagination">
                    <button
                      type="button"
                      onClick={() => setUsersPage((p) => Math.max(1, p - 1))}
                      disabled={usersPage <= 1}
                      aria-label="Previous page"
                      className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setUsersPage((p) => Math.min(totalPages, p + 1))}
                      disabled={usersPage >= totalPages}
                      aria-label="Next page"
                      className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
                    >
                      <ChevronRight size={14} />
                    </button>
                  </nav>
                </>
              ) : undefined
            }
          />
        </>
      )}

      {/* ---- Tab: Data Processing Register ---- */}
      {tab === "datamap" && dataMap && (
        <section className={`${CARD} px-0 py-0 overflow-hidden`}>
          <div className="border-b border-(--line) px-[22px] py-[18px]">
            <h3 className={`${CARD_TITLE} flex items-center gap-2`}>
              <FileText size={16} className="text-(--good)" />
              Article 30, Records of Processing Activities
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className={TH}>Data Category</th>
                  <th className={TH}>Table</th>
                  <th className={TH}>PII Fields</th>
                  <th className={TH}>Retention Policy</th>
                  <th className={TH}>Legal Basis</th>
                  <th className={`${TH} text-right`}>Records</th>
                </tr>
              </thead>
              <tbody>
                {dataMap.entries.map((entry) => (
                  <tr key={entry.table} className={TROW}>
                    <td className={`${TD} font-medium`}>{entry.category}</td>
                    <td className={`${TD} font-(family-name:--mono) text-(--t-2)`}>
                      {entry.table}
                    </td>
                    <td className={TD}>
                      <div className="flex flex-wrap gap-1">
                        {entry.pii_fields.map((f) => (
                          <span
                            key={f}
                            className="rounded-[8px] border-0 bg-(--bad-s) px-1.5 py-0.5 font-(family-name:--mono) text-[10px] text-(--bad)"
                          >
                            {f}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className={`${TD} text-(--t-2)`}>{entry.retention_policy}</td>
                    <td className={`${TD} text-(--t-2)`}>{entry.legal_basis}</td>
                    <td className={`${TD} text-right font-(family-name:--mono) text-(--t-2)`}>
                      {entry.record_count.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ---- User detail / action modal ---- */}
      <Modal open={Boolean(selectedUser || detailLoading)} onClose={closeDetail}>
        {detailLoading && !selectedUser ? (
          <div className="p-12 text-center">
            <Loader2 size={24} className="mx-auto animate-spin text-(--t-2)" />
          </div>
        ) : selectedUser ? (
          <div className="max-h-[85vh] space-y-6 overflow-y-auto p-6">
            {/* Header */}
            <div className="flex items-start justify-between">
              <div>
                <h3 className={CARD_TITLE}>User #{selectedUser.user_id}</h3>
                <p className="mt-0.5 text-[13px] text-(--t-2)">{selectedUser.email}</p>
              </div>
              <button
                onClick={closeDetail}
                className="rounded-(--r-sm) p-2 text-(--t-2) transition-colors hover:bg-(--line-2)"
              >
                <X size={16} />
              </button>
            </div>

            {/* Summary grid */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {[
                { label: "Assessments", value: selectedUser.audit_count },
                { label: "Emails", value: selectedUser.email_count },
                { label: "Payments", value: selectedUser.payment_count },
                {
                  label: "Subscription",
                  value: selectedUser.has_subscription ? "Yes" : "No",
                },
              ].map((s) => (
                <div
                  key={s.label}
                  className="rounded-(--r-md) border-0 bg-[#EEF1F6] p-3 text-center"
                >
                  <p className={MICRO_LABEL}>{s.label}</p>
                  <p className="mt-1 text-sm font-semibold text-(--t-1)">{s.value}</p>
                </div>
              ))}
            </div>

            {selectedUser.anonymized_at && (
              <Alert variant="warning">
                <AlertTriangle />
                <AlertDescription>
                  This user was anonymized on{" "}
                  {new Date(selectedUser.anonymized_at).toLocaleDateString()}.
                </AlertDescription>
              </Alert>
            )}

            {/* GDPR Actions */}
            <div className="space-y-4">
              <h4 className={`${CARD_TITLE} flex items-center gap-2`}>
                <Shield size={14} className="text-(--good)" />
                GDPR actions
              </h4>

              {/* Export */}
              <div className="rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[13.5px] font-semibold text-(--t-1)">
                      Subject Access Request (SAR)
                    </p>
                    <p className="mt-0.5 text-xs text-(--t-3)">
                      Export all user data as JSON (Article 15)
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleExport(selectedUser.user_id)}
                    disabled={exporting}
                  >
                    {exporting ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Download size={14} />
                    )}
                    {exporting ? "Generating…" : "Export data"}
                  </Button>
                </div>
                {exportData && (
                  <div className="mt-3 border-t border-(--line) pt-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-(--good)">
                        Export ready ({Object.keys(exportData).length} categories)
                      </span>
                      <Button variant="ghost" size="sm" onClick={handleDownloadExport}>
                        <Download size={12} /> Download JSON
                      </Button>
                    </div>
                  </div>
                )}
              </div>

              {/* Anonymize */}
              {!selectedUser.anonymized_at && (
                <div className="rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4">
                  <div>
                    <p className="flex items-center gap-2 text-[13.5px] font-semibold text-(--t-1)">
                      <ShieldOff size={14} className="text-(--bad)" />
                      Anonymize User
                    </p>
                    <p className="mt-0.5 text-xs text-(--t-3)">
                      Replace all PII with hashed values. This is{" "}
                      <strong className="text-(--bad)">irreversible</strong>. Audit scores and
                      timestamps are preserved for analytics.
                    </p>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <input
                      type="text"
                      value={anonymizeEmail}
                      onChange={(e) => setAnonymizeEmail(e.target.value)}
                      placeholder="Type user email to confirm…"
                      className={`${WINPUT} h-9 flex-1 text-[12.5px]`}
                    />
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => handleAnonymize(selectedUser.user_id)}
                      disabled={anonymizing || anonymizeEmail !== selectedUser.email}
                    >
                      {anonymizing ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <UserX size={14} />
                      )}
                      Anonymize
                    </Button>
                  </div>
                </div>
              )}

              {/* Delete link */}
              <div className="flex items-center gap-1.5 text-xs text-(--t-3)">
                <Trash2 size={12} />
                Full account deletion is available in the{" "}
                <a href="/admin/users" className="text-(--bad) underline hover:opacity-80">
                  Users admin panel
                </a>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
