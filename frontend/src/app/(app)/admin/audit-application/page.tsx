"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/custom-auth";
import {
  ExternalLink,
  Filter,
  RefreshCcw,
  Globe,
  User,
  ShieldCheck,
  ChevronRight,
  ChevronLeft,
  Clock,
  Lock as LockIcon,
  Database,
  Layers,
  Zap,
  AlertTriangle,
} from "lucide-react";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { ClientSafeDate } from "@/lib/dateFormat";
import { useDebounce } from "@/hooks/useDebounce";
import { cx } from "@/components/ui/utils";
import Button from "@/components/ui/Button";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AdminTableSkeleton } from "@/components/admin/AdminTableSkeleton";
import { getTierShort } from "@/constants/tiers";

type AdminAuditEntry = {
  id: number;
  user_id: number;
  user_email: string;
  url: string;
  audit_target_type: string | null;
  target_name: string | null;
  target_url: string | null;
  geo_score: number;
  seo_score: number;
  aeo_score: number;
  provider: string | null;
  tier: string | null;
  requested_tier: string | null;
  grounding_profile: string | null;
  dual_track_grounding_enabled: boolean;
  fallback_reason: string | null;
  track_a_claim_count: number | null;
  track_b_claim_count: number | null;
  dual_track_rollout_mode: string | null;
  dual_track_execution_mode: string | null;
  created_at: string;
  sanitized_at: string | null;
  has_screenshot: boolean;
};

type AdminAuditListResponse = {
  audits: AdminAuditEntry[];
  page: number;
  page_size: number;
  total: number;
};

type AuditFilters = {
  userEmail: string;
  userId: string;
  urlContains: string;
  provider: string;
  tier: string;
  groundingProfile: string;
  dualTrackEnabled: "all" | "enabled" | "disabled";
  fallbackReason: string;
  startDate: string;
  endDate: string;
};

const defaultFilters: AuditFilters = {
  userEmail: "",
  userId: "",
  urlContains: "",
  provider: "",
  tier: "",
  groundingProfile: "",
  dualTrackEnabled: "all",
  fallbackReason: "",
  startDate: "",
  endDate: "",
};

const GROUNDING_PROFILE_OPTIONS = [
  "shadow_dual_track",
  "single_track_fallback",
  "legacy_single_track",
  "utc_unavailable_fallback",
];

/* -------------------------------------------------------------------------- */
/*  Design tokens                                                              */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const WINPUT =
  "field-focus-ring h-9 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[10px] text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const PAGER_BTN =
  "inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-(--r-sm) px-2 font-(family-name:--mono) text-[11px] text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40";

const formatScore = (score: number) => {
  const normalized = score <= 1 ? score * 100 : score;
  return Math.round(normalized);
};

const formatAuditLabel = (value: string | null | undefined) =>
  value ? value.replace(/_/g, " ") : "not recorded";

const getGroundingProfileChipClass = (profile: string | null | undefined) => {
  if (!profile) return `${CHIP} text-(--t-3) bg-(--paper)`;
  if (profile === "shadow_dual_track") return `${CHIP} text-(--purple) bg-(--purple-s)`;
  if (profile.includes("fallback")) return `${CHIP} text-(--warn) bg-(--warn-s)`;
  return `${CHIP} text-(--purple) bg-(--purple-s)`;
};

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className={`${MICRO_LABEL} block`}>{label}</label>
      {children}
    </div>
  );
}

export default function AdminAuditApplicationPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [filters, setFilters] = useState<AuditFilters>(defaultFilters);
  const debouncedFilters = useDebounce(filters, 500);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [data, setData] = useState<AdminAuditListResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access audit records.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const buildDateParam = (value: string, isEnd: boolean) => {
    if (!value) return "";
    const dateValue = isEnd ? `${value}T23:59:59` : `${value}T00:00:00`;
    try {
      return new Date(dateValue).toISOString();
    } catch {
      return "";
    }
  };

  const loadAudits = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));

      if (debouncedFilters.userEmail) params.set("user_email", debouncedFilters.userEmail);
      if (debouncedFilters.userId) params.set("user_id", debouncedFilters.userId);
      if (debouncedFilters.urlContains) params.set("url_contains", debouncedFilters.urlContains);
      if (debouncedFilters.provider) params.set("provider", debouncedFilters.provider);
      if (debouncedFilters.tier) params.set("tier", debouncedFilters.tier);
      if (debouncedFilters.groundingProfile) {
        params.set("grounding_profile", debouncedFilters.groundingProfile);
      }
      if (debouncedFilters.dualTrackEnabled === "enabled") {
        params.set("dual_track_grounding_enabled", "true");
      }
      if (debouncedFilters.dualTrackEnabled === "disabled") {
        params.set("dual_track_grounding_enabled", "false");
      }
      if (debouncedFilters.fallbackReason) {
        params.set("fallback_reason", debouncedFilters.fallbackReason);
      }
      if (debouncedFilters.startDate)
        params.set("start_date", buildDateParam(debouncedFilters.startDate, false));
      if (debouncedFilters.endDate)
        params.set("end_date", buildDateParam(debouncedFilters.endDate, true));

      const response = await fetch(`/api/admin/audits?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load audits.");
      }
      const payload = (await response.json()) as AdminAuditListResponse;
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load audits.");
    } finally {
      setIsLoading(false);
    }
  }, [debouncedFilters, getAuthHeaders, isSignedIn, page, pageSize]);

  useEffect(() => {
    loadAudits();
  }, [loadAudits]);

  useEffect(() => {
    setPage(1);
  }, [debouncedFilters, pageSize]);

  const totalPages = useMemo(() => {
    if (!data) return 1;
    return Math.max(1, Math.ceil(data.total / data.page_size));
  }, [data]);

  const isBusy = isLoading || isGuardLoading;
  const clearFilters = () => {
    setFilters(defaultFilters);
    setPage(1);
  };

  const columns: SignalDataTableColumn<AdminAuditEntry>[] = [
    {
      key: "audit",
      header: "Audit",
      renderCell: (audit) => (
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-(--r-sm) border-0 bg-[#EEF1F6] text-(--t-3)">
            <Globe className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-(--t-1)">Audit {audit.id}</p>
            <p className="max-w-[220px] truncate text-[11px] text-(--t-3)">
              {(audit.target_name || audit.target_url || audit.url).replace(/^https?:\/\//, "")}
            </p>
            <p className={`${MONO_META} mt-0.5`}>{formatAuditLabel(audit.audit_target_type)}</p>
          </div>
        </div>
      ),
    },
    {
      key: "user",
      header: "User",
      renderCell: (audit) => (
        <>
          <div className="mb-1 flex items-center gap-1.5">
            <User size={12} className="text-(--t-3)" />
            <span className="max-w-[180px] truncate text-[12.5px] font-semibold text-(--t-1)">
              {audit.user_email}
            </span>
          </div>
          <p className={MONO_META}>ID: {audit.user_id}</p>
        </>
      ),
    },
    {
      key: "scores",
      header: "Scores",
      renderCell: (audit) => (
        <div className="flex flex-wrap gap-1.5">
          <span className={`${CHIP} text-(--link) bg-(--purple-s)`}>
            AI visibility {formatScore(audit.geo_score)}
          </span>
          <span className={`${CHIP} text-(--purple) bg-(--purple-s)`}>
            SEO {formatScore(audit.seo_score)}
          </span>
          <span className={`${CHIP} text-(--warn) bg-(--warn-s)`}>
            AI answers {formatScore(audit.aeo_score)}
          </span>
        </div>
      ),
    },
    {
      key: "model",
      header: "Model / tier",
      renderCell: (audit) => (
        <>
          <p className={`${MONO_META} text-(--t-1)`}>{audit.provider ?? "generic"}</p>
          <div className="mt-1 flex items-center gap-1.5">
            <div
              className={cx(
                "h-1.5 w-1.5 rounded-full",
                audit.tier === "deep" || audit.tier === "deep_judgment"
                  ? "bg-(--purple)"
                  : "bg-(--line-2)"
              )}
            />
            <span className={MONO_META}>{getTierShort(audit.tier)}</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className={`${CHIP} text-(--t-2) bg-(--paper)`}>
              <Layers size={10} />
              Requested {getTierShort(audit.requested_tier ?? audit.tier)}
            </span>
            {audit.dual_track_execution_mode && (
              <span className={`${CHIP} text-(--purple) bg-(--purple-s)`}>
                <Zap size={10} />
                {formatAuditLabel(audit.dual_track_execution_mode)}
              </span>
            )}
          </div>
        </>
      ),
    },
    {
      key: "created",
      header: "Created",
      renderCell: (audit) => (
        <>
          <div className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold text-(--t-2)">
            <Clock size={12} className="text-(--t-3)" />
            <ClientSafeDate date={audit.created_at} />
          </div>
          <p className={MICRO_LABEL}>Assessment completed</p>
        </>
      ),
    },
    {
      key: "status",
      header: "Status",
      renderCell: (audit) => (
        <div className="space-y-2">
          {audit.sanitized_at ? (
            <span className={`${CHIP} text-(--good) bg-(--good-s)`}>
              <ShieldCheck size={10} />
              Sanitized
            </span>
          ) : (
            <span
              className={cx(
                CHIP,
                audit.has_screenshot
                  ? "text-(--purple) bg-(--purple-s)"
                  : "text-(--t-3) bg-(--paper)"
              )}
            >
              {audit.has_screenshot ? "Screenshot" : "No screenshot"}
            </span>
          )}
          <div className="flex flex-wrap gap-1.5">
            <span className={getGroundingProfileChipClass(audit.grounding_profile)}>
              <Layers size={10} />
              {formatAuditLabel(audit.grounding_profile)}
            </span>
            <span
              className={cx(
                CHIP,
                audit.dual_track_grounding_enabled
                  ? "text-(--good) bg-(--good-s)"
                  : "text-(--t-3) bg-(--paper)"
              )}
            >
              <ShieldCheck size={10} />
              {audit.dual_track_grounding_enabled ? "Dual-track on" : "Dual-track off"}
            </span>
          </div>
          {(audit.track_a_claim_count != null || audit.track_b_claim_count != null) && (
            <p className={MONO_META}>
              A {audit.track_a_claim_count ?? 0} / B {audit.track_b_claim_count ?? 0}
            </p>
          )}
          {audit.fallback_reason && (
            <span className={`${CHIP} text-(--warn) bg-(--warn-s)`}>
              <AlertTriangle size={10} />
              {formatAuditLabel(audit.fallback_reason)}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      renderCell: (audit) => (
        <Link href={`/admin/audit-application/${audit.id}`}>
          <Button
            variant="ghost"
            className="h-8 w-8 p-0 text-(--t-3) hover:text-(--purple)"
            aria-label={`Open audit ${audit.id}`}
          >
            <ExternalLink size={14} />
          </Button>
        </Link>
      ),
    },
  ];

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <>
          <Link href="/admin/audit-retention">
            <Button variant="ghost" size="sm">
              <span className="max-sm:hidden">Retention settings</span>
              <span className="sm:hidden">Retention</span>
            </Button>
          </Link>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void loadAudits()}
            disabled={isLoading}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCcw size={14} className={isLoading ? "animate-spin" : ""} />
          </Button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [isLoading, loadAudits, setHeader]);

  return (
    <>
      <DashboardPageIntro icon={Database} title="Audit history">
        View and manage all audit records across the platform.
      </DashboardPageIntro>

      {/* Filters */}
      <div className={WSEC}>
        <div className="mb-5 flex items-center justify-between">
          <h2 className="m-0 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
            <Filter size={14} className="text-(--purple)" />
            Search filters
          </h2>
          <button
            onClick={clearFilters}
            className={`${MONO_META} underline underline-offset-4 transition-colors hover:text-(--purple)`}
          >
            Clear filters
          </button>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          <FilterField label="Client email">
            <input
              type="text"
              placeholder="user@example.com"
              value={filters.userEmail}
              onChange={(e) => setFilters((p) => ({ ...p, userEmail: e.target.value }))}
              className={WINPUT}
            />
          </FilterField>
          <FilterField label="Internal ID">
            <input
              type="text"
              placeholder="000"
              value={filters.userId}
              onChange={(e) => setFilters((p) => ({ ...p, userId: e.target.value }))}
              className={WINPUT}
            />
          </FilterField>
          <FilterField label="URL fragment">
            <input
              type="text"
              placeholder="example.com"
              value={filters.urlContains}
              onChange={(e) => setFilters((p) => ({ ...p, urlContains: e.target.value }))}
              className={WINPUT}
            />
          </FilterField>
          <FilterField label="AI provider">
            <input
              type="text"
              placeholder="openai"
              value={filters.provider}
              onChange={(e) => setFilters((p) => ({ ...p, provider: e.target.value }))}
              className={WINPUT}
            />
          </FilterField>
          <FilterField label="Tier">
            <input
              type="text"
              placeholder="pro"
              value={filters.tier}
              onChange={(e) => setFilters((p) => ({ ...p, tier: e.target.value }))}
              className={WINPUT}
            />
          </FilterField>
          <FilterField label="Grounding profile">
            <NativeSelect
              variant="auth"
              aria-label="Grounding profile filter"
              value={filters.groundingProfile}
              onChange={(e) =>
                setFilters((current) => ({ ...current, groundingProfile: e.target.value }))
              }
              className="h-9 w-full text-[12.5px]"
            >
              <option value="">All profiles</option>
              {GROUNDING_PROFILE_OPTIONS.map((profile) => (
                <option key={profile} value={profile}>
                  {formatAuditLabel(profile)}
                </option>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField label="Dual-track">
            <NativeSelect
              variant="auth"
              aria-label="Dual-track enabled filter"
              value={filters.dualTrackEnabled}
              onChange={(e) =>
                setFilters((current) => ({
                  ...current,
                  dualTrackEnabled: e.target.value as AuditFilters["dualTrackEnabled"],
                }))
              }
              className="h-9 w-full text-[12.5px]"
            >
              <option value="all">All states</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </NativeSelect>
          </FilterField>
          <FilterField label="Fallback reason">
            <input
              type="text"
              aria-label="Fallback reason filter"
              placeholder="judge"
              value={filters.fallbackReason}
              onChange={(e) =>
                setFilters((current) => ({ ...current, fallbackReason: e.target.value }))
              }
              className={WINPUT}
            />
          </FilterField>
          <FilterField label="Start date">
            <input
              type="date"
              value={filters.startDate}
              onChange={(e) => setFilters((p) => ({ ...p, startDate: e.target.value }))}
              className={WINPUT}
            />
          </FilterField>
          <FilterField label="End date">
            <input
              type="date"
              value={filters.endDate}
              onChange={(e) => setFilters((p) => ({ ...p, endDate: e.target.value }))}
              className={WINPUT}
            />
          </FilterField>
        </div>

        {error && (
          <Alert variant="destructive" className="mt-4">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </div>

      {/* Audit records */}
      {isLoading && !data ? (
        <AdminTableSkeleton rows={6} columns={5} />
      ) : (
        <SignalDataTable
          columns={columns}
          rows={data?.audits ?? []}
          rowKey={(audit) => audit.id}
          emptyLabel="No audits found. Try adjusting your search filters."
          tools={
            <NativeSelect
              variant="auth"
              aria-label="Rows per page"
              value={pageSize}
              onChange={(event) => setPageSize(Number(event.target.value))}
              className="h-8 w-auto text-[12.5px]"
            >
              {[10, 25, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size} rows
                </option>
              ))}
            </NativeSelect>
          }
          metaLabel={`${data?.audits.length ?? 0} / ${data?.total ?? 0} audits`}
          pageSize={pageSize}
          footer={
            <>
              <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
                Page {page} of {totalPages}
              </span>
              <nav className="ms-auto inline-flex items-center gap-1" aria-label="Pagination">
                <button
                  type="button"
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                  disabled={page <= 1 || isBusy}
                  aria-label="Previous page"
                  className={PAGER_BTN}
                >
                  <ChevronLeft size={14} /> Previous
                </button>
                <button
                  type="button"
                  onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                  disabled={page >= totalPages || isBusy}
                  aria-label="Next page"
                  className={PAGER_BTN}
                >
                  Next <ChevronRight size={14} />
                </button>
              </nav>
            </>
          }
        />
      )}

      {!isAdmin && !isGuardLoading && (
        <Alert variant="warning">
          <LockIcon className="h-4 w-4" />
          <AlertDescription>
            Access denied: admin privileges required to view audit records.
          </AlertDescription>
        </Alert>
      )}
    </>
  );
}
