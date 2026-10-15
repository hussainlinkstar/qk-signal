"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Building2,
  Search,
  ChevronRight,
  ChevronLeft,
  Users,
  FolderKanban,
  Crown,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { ClientSafeDate } from "@/lib/dateFormat";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";

type AdminWorkspace = {
  id: number;
  name: string;
  owner_id: number;
  owner_email: string;
  plan_name: string;
  member_count: number;
  project_count: number;
  created_at: string;
};

type AdminWorkspacesResponse = {
  items: AdminWorkspace[];
  total: number;
  page: number;
  per_page: number;
};

const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

const PLAN_BADGE_STYLES: Record<string, string> = {
  plan_standard: `${CHIP} text-(--t-2) bg-(--line-2)`,
  plan_specialist: `${CHIP} text-(--purple) bg-(--purple-s)`,
  plan_executive: `${CHIP} text-(--warn) bg-(--warn-s)`,
};

const PLAN_DISPLAY_NAMES: Record<string, string> = {
  plan_standard: "Standard",
  plan_specialist: "Specialist",
  plan_executive: "Executive",
};

function PlanBadge({ plan }: { plan: string }) {
  const style = PLAN_BADGE_STYLES[plan] ?? PLAN_BADGE_STYLES.plan_standard;
  const label = PLAN_DISPLAY_NAMES[plan] ?? plan.replace(/_/g, " ");
  return (
    <span className={style}>
      <Crown size={10} />
      {label}
    </span>
  );
}

export default function AdminWorkspacesPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(25);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin data.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadWorkspaces = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({
        page: String(page),
        per_page: String(perPage),
      });
      if (query.trim()) {
        params.set("search", query.trim());
      }
      const response = await fetch(`/api/admin/workspaces?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load workspaces.");
      }
      const payload = (await response.json()) as AdminWorkspacesResponse;
      setWorkspaces(payload.items);
      setTotal(payload.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load workspaces.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn, page, perPage, query]);

  useEffect(() => {
    loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    setPage(1);
  }, [query, perPage]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / perPage)), [total, perPage]);

  const controlsDisabled = !isAdmin || isLoading || isGuardLoading;

  const columns: SignalDataTableColumn<AdminWorkspace>[] = [
    {
      key: "workspace",
      header: "Workspace",
      sortable: true,
      sortValue: (ws) => ws.name,
      renderCell: (ws) => (
        <Link href={`/admin/workspaces/${ws.id}`} className="group/link flex flex-col">
          <span className="font-semibold text-(--t-1) transition-colors group-hover/link:text-(--purple)">
            {ws.name}
          </span>
          <span className="font-(family-name:--mono) text-[10.5px] text-(--t-3)">ID: {ws.id}</span>
        </Link>
      ),
    },
    {
      key: "owner",
      header: "Owner",
      renderCell: (ws) => <span className="text-(--t-2)">{ws.owner_email}</span>,
    },
    {
      key: "plan",
      header: "Plan",
      renderCell: (ws) => <PlanBadge plan={ws.plan_name} />,
    },
    {
      key: "members",
      header: "Members",
      sortable: true,
      sortValue: (ws) => ws.member_count,
      renderCell: (ws) => (
        <div className="flex items-center gap-1.5 text-(--t-2)">
          <Users size={14} className="text-(--t-3)" />
          <span className="font-semibold">{ws.member_count}</span>
        </div>
      ),
    },
    {
      key: "projects",
      header: "Projects",
      sortable: true,
      sortValue: (ws) => ws.project_count,
      renderCell: (ws) => (
        <div className="flex items-center gap-1.5 text-(--t-2)">
          <FolderKanban size={14} className="text-(--t-3)" />
          <span className="font-semibold">{ws.project_count}</span>
        </div>
      ),
    },
    {
      key: "created",
      header: "Created",
      sortable: true,
      sortValue: (ws) => ws.created_at,
      renderCell: (ws) => (
        <span className="text-(--t-2)">
          <ClientSafeDate date={ws.created_at} />
        </span>
      ),
    },
    {
      key: "open",
      header: "",
      align: "right",
      renderCell: (ws) => (
        <Link
          href={`/admin/workspaces/${ws.id}`}
          className="inline-flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--t-2) transition-colors hover:border-(--purple) hover:text-(--purple)"
          title="View workspace"
        >
          <ChevronRight size={14} />
        </Link>
      ),
    },
  ];

  return (
    <>
      <DashboardPageIntro icon={Building2} title="Workspaces">
        Browse and manage all workspaces on the platform. View membership rosters, projects, and
        usage metrics per workspace.
      </DashboardPageIntro>

      {error ? (
        <Alert variant="destructive">
          <Building2 />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <SignalDataTable
        columns={columns}
        rows={workspaces}
        rowKey={(ws) => ws.id}
        emptyLabel={isLoading ? "Loading workspaces..." : "No workspaces found."}
        tools={
          <>
            <div className="relative max-w-[250px] flex-1">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-(--t-3)"
              />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name or owner email..."
                aria-label="Search workspaces"
                className="field-focus-ring h-8 w-full rounded-(--r-sm) border-0 bg-[#EEF1F6] pl-8 pr-2.5 text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c9cef7]"
              />
            </div>
            <NativeSelect
              variant="auth"
              value={perPage}
              onChange={(e) => setPerPage(Number(e.target.value))}
              className="h-8 w-auto text-[12.5px]"
              aria-label="Workspaces per page"
            >
              {[10, 25, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size} Workspaces
                </option>
              ))}
            </NativeSelect>
          </>
        }
        metaLabel={`${total} workspaces`}
        pageSize={perPage}
        footer={
          <>
            <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
              {workspaces.length} / {total} · Page {page} of {totalPages}
            </span>
            <nav className="ms-auto inline-flex items-center gap-1" aria-label="Pagination">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || controlsDisabled}
                aria-label="Previous page"
                className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
              >
                <ChevronLeft size={14} />
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || controlsDisabled}
                aria-label="Next page"
                className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
              >
                <ChevronRight size={14} />
              </button>
            </nav>
          </>
        }
      />
    </>
  );
}
