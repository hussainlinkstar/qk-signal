"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  Users,
  Crown,
  Pencil,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { ClientSafeDate } from "@/lib/dateFormat";
import Button from "@/components/ui/Button";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import SignalTabs from "@/components/signal/SignalTabs";
import Modal from "@/components/ui/Modal";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";

/* ── Types ──────────────────────────────────────────────────────── */

type WorkspaceMember = {
  user_id: number;
  email: string;
  name: string | null;
  role: string;
  joined_at: string;
};

type WorkspaceProject = {
  id: number;
  name: string;
  domain_url: string | null;
  created_at: string;
};

type UsageSummary = {
  total_audits: number;
  audits_this_month: number;
  projects_count: number;
  member_count: number;
};

type BillingInfo = {
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  plan_name: string;
  subscription_status: string | null;
};

type WorkspaceDetail = {
  id: number;
  name: string;
  owner_id: number;
  owner_email: string;
  plan_name: string;
  created_at: string;
  members: WorkspaceMember[];
  projects: WorkspaceProject[];
  usage_summary: UsageSummary;
  billing: BillingInfo;
};

type AuditHistoryItem = {
  id: number;
  url: string;
  audit_type: string | null;
  geo_score: number | null;
  seo_score: number | null;
  aeo_score: number | null;
  project_name: string | null;
  created_at: string | null;
};

/* ── Style constants ───────────────────────────────────────────── */

const WSTAT = "flex flex-col gap-1 rounded-[22px] border-0 bg-white px-4 py-3";
const WSTAT_VALUE =
  "font-(family-name:--disp) text-[20px] font-bold leading-none tracking-[-0.02em] text-(--t-1)";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const FIELD_LABEL = `mb-2 block ${MICRO_LABEL}`;
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const CHIP_NEUTRAL = `${CHIP} text-(--t-2) bg-(--line-2)`;

/* ── Plan badge styles ──────────────────────────────────────────── */

const PLAN_BADGE_STYLES: Record<string, string> = {
  plan_standard: CHIP_NEUTRAL,
  plan_specialist: `${CHIP} text-(--purple) bg-(--purple-s)`,
  plan_executive: `${CHIP} text-(--warn) bg-(--warn-s)`,
};

const PLAN_DISPLAY_NAMES: Record<string, string> = {
  plan_standard: "Standard",
  plan_specialist: "Specialist",
  plan_executive: "Executive",
};

/* ── Tab definitions ────────────────────────────────────────────── */

type TabKey = "members" | "projects" | "audits";

const TABS: { id: TabKey; label: string }[] = [
  { id: "members", label: "Members" },
  { id: "projects", label: "Projects" },
  { id: "audits", label: "Audit History" },
];

/* ── Stat card ──────────────────────────────────────────────────── */

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className={WSTAT}>
      <div className="flex items-center justify-between gap-2">
        <span className={WSTAT_VALUE}>{value}</span>
      </div>
      <span className={MICRO_LABEL}>{label}</span>
    </div>
  );
}

/* ── Role badge ─────────────────────────────────────────────────── */

function RoleBadge({ role }: { role: string }) {
  const isAdmin = role === "ADMIN";
  return (
    <span className={isAdmin ? `${CHIP} text-(--purple) bg-(--purple-s)` : CHIP_NEUTRAL}>
      {isAdmin ? <Crown size={10} /> : <Users size={10} />}
      {role}
    </span>
  );
}

/* ── Edit name modal ──────────────────────────────────────────── */

function EditNameModal({
  isOpen,
  currentName,
  onClose,
  onSave,
  isSaving,
}: {
  isOpen: boolean;
  currentName: string;
  onClose: () => void;
  onSave: (name: string) => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(currentName);

  useEffect(() => {
    setName(currentName);
  }, [currentName, isOpen]);

  return (
    <Modal open={isOpen} onClose={onClose} title="Edit workspace">
      <div className="space-y-4">
        <div>
          <label className={FIELD_LABEL}>Workspace name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} className={WINPUT} />
        </div>
        <div className="flex justify-end gap-3 border-t border-(--line-2) pt-4">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => onSave(name)}
            disabled={isSaving || !name.trim()}
          >
            {isSaving ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/* ── Delete workspace modal ─────────────────────────────────────── */

function DeleteWorkspaceModal({
  isOpen,
  workspace,
  workspacesList,
  onClose,
  onConfirm,
  isDeleting,
}: {
  isOpen: boolean;
  workspace: WorkspaceDetail;
  workspacesList: { id: number; name: string }[];
  onClose: () => void;
  onConfirm: (action: "delete" | "move", targetId?: number) => void;
  isDeleting: boolean;
}) {
  const [projectAction, setProjectAction] = useState<"delete" | "move">("delete");
  const [targetWorkspaceId, setTargetWorkspaceId] = useState<number | "">("");

  const hasProjects = workspace.usage_summary.projects_count > 0;

  // Reset when opened
  useEffect(() => {
    if (isOpen) {
      setProjectAction("delete");
      setTargetWorkspaceId("");
    }
  }, [isOpen]);

  const canSubmit =
    !hasProjects ||
    projectAction === "delete" ||
    (projectAction === "move" && targetWorkspaceId !== "");

  return (
    <Modal open={isOpen} onClose={onClose} title="Delete workspace">
      <div className="space-y-4 text-sm text-(--t-2)">
        <Alert variant="destructive">
          <AlertDescription>
            Are you sure you want to delete the workspace <strong>{workspace.name}</strong>? This
            action cannot be undone.
          </AlertDescription>
        </Alert>

        {hasProjects && (
          <div className="space-y-4 border-t border-(--line-2) pt-4">
            <p className="font-semibold text-(--t-1)">
              This workspace contains {workspace.usage_summary.projects_count} project(s).
            </p>
            <div className="space-y-3">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="radio"
                  name="projectAction"
                  value="delete"
                  checked={projectAction === "delete"}
                  onChange={() => setProjectAction("delete")}
                  className="w-4 h-4 accent-(--bad)"
                />
                <span>Delete all projects permanently</span>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="radio"
                  name="projectAction"
                  value="move"
                  checked={projectAction === "move"}
                  onChange={() => setProjectAction("move")}
                  className="w-4 h-4 accent-(--purple)"
                />
                <span>Move projects to another workspace</span>
              </label>
            </div>

            {projectAction === "move" && (
              <div className="pl-7">
                <NativeSelect
                  variant="auth"
                  value={targetWorkspaceId}
                  onChange={(e) => setTargetWorkspaceId(Number(e.target.value) || "")}
                >
                  <option value="" disabled>
                    Select target workspace...
                  </option>
                  {workspacesList
                    .filter((w) => w.id !== workspace.id)
                    .map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name} (ID: {w.id})
                      </option>
                    ))}
                </NativeSelect>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-3 border-t border-(--line-2) pt-4">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isDeleting}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() =>
              onConfirm(
                projectAction,
                typeof targetWorkspaceId === "number" ? targetWorkspaceId : undefined
              )
            }
            disabled={isDeleting || !canSubmit}
          >
            {isDeleting ? "Deleting..." : "Delete workspace"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */

export default function AdminWorkspaceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const workspaceId = params?.workspaceId as string;

  const { getToken, isSignedIn } = useAuth();
  const { isAdmin } = useAdminAccess();

  const [workspace, setWorkspace] = useState<WorkspaceDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("members");

  // Audit history state
  const [auditItems, setAuditItems] = useState<AuditHistoryItem[]>([]);
  const [auditPage, setAuditPage] = useState(1);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditLoading, setAuditLoading] = useState(false);
  const auditPageSize = 25;

  // Edit modal
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);

  // Delete modal
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteSaving, setDeleteSaving] = useState(false);
  const [workspacesList, setWorkspacesList] = useState<{ id: number; name: string }[]>([]);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("Not authenticated.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadWorkspace = useCallback(async () => {
    if (!isSignedIn || !workspaceId) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/admin/workspaces/${workspaceId}`, {
        headers,
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load workspace.");
      }
      setWorkspace(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load workspace.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn, workspaceId]);

  const loadAuditHistory = useCallback(async () => {
    if (!isSignedIn || !workspaceId) return;
    setAuditLoading(true);
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({
        page: String(auditPage),
        page_size: String(auditPageSize),
      });
      const res = await fetch(`/api/admin/workspaces/${workspaceId}/audit-history?${params}`, {
        headers,
      });
      if (res.ok) {
        const data = await res.json();
        setAuditItems(data.items);
        setAuditTotal(data.total);
      }
    } catch {
      // non-critical, silently fail
    } finally {
      setAuditLoading(false);
    }
  }, [getAuthHeaders, isSignedIn, workspaceId, auditPage]);

  const loadWorkspacesList = useCallback(async () => {
    if (!isSignedIn || !isAdmin) return;
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/admin/workspaces?per_page=1000`, { headers });
      if (res.ok) {
        const data = await res.json();
        setWorkspacesList(data.items || []);
      }
    } catch {
      // silently fail
    }
  }, [getAuthHeaders, isSignedIn, isAdmin]);

  useEffect(() => {
    loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (isAdmin && workspace) {
      loadWorkspacesList();
    }
  }, [isAdmin, workspace, loadWorkspacesList]);

  useEffect(() => {
    if (activeTab === "audits") {
      loadAuditHistory();
    }
  }, [activeTab, loadAuditHistory]);

  const handleSaveName = useCallback(
    async (newName: string) => {
      if (!workspaceId) return;
      setEditSaving(true);
      try {
        const headers = await getAuthHeaders();
        const res = await fetch(`/api/admin/workspaces/${workspaceId}`, {
          method: "PATCH",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ name: newName }),
        });
        if (!res.ok) {
          const p = await res.json().catch(() => null);
          throw new Error(p?.detail ?? "Unable to update workspace.");
        }
        setEditOpen(false);
        await loadWorkspace();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Update failed.");
      } finally {
        setEditSaving(false);
      }
    },
    [getAuthHeaders, workspaceId, loadWorkspace]
  );

  const handleDeleteWorkspace = useCallback(
    async (action: "delete" | "move", targetId?: number) => {
      if (!workspaceId) return;
      setDeleteSaving(true);
      try {
        const headers = await getAuthHeaders();
        const res = await fetch(`/api/admin/workspaces/${workspaceId}/delete`, {
          method: "POST",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({
            project_action: action,
            target_workspace_id: targetId,
          }),
        });

        if (!res.ok) {
          const p = await res.json().catch(() => null);
          throw new Error(p?.detail ?? "Unable to delete workspace.");
        }

        setDeleteOpen(false);
        router.push("/admin/workspaces");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed.");
        setDeleteOpen(false);
      } finally {
        setDeleteSaving(false);
      }
    },
    [getAuthHeaders, workspaceId, router]
  );

  const auditTotalPages = Math.max(1, Math.ceil(auditTotal / auditPageSize));

  const memberColumns: SignalDataTableColumn<WorkspaceMember>[] = [
    {
      key: "email",
      header: "Email",
      sortable: true,
      sortValue: (m) => m.email,
      renderCell: (m) => <span className="text-(--t-1)">{m.email}</span>,
    },
    {
      key: "name",
      header: "Name",
      renderCell: (m) => <span className="text-(--t-2)">{m.name || "-"}</span>,
    },
    {
      key: "role",
      header: "Role",
      renderCell: (m) => <RoleBadge role={m.role} />,
    },
    {
      key: "joined",
      header: "Joined",
      sortable: true,
      sortValue: (m) => m.joined_at,
      renderCell: (m) => (
        <span className="text-(--t-2)">
          <ClientSafeDate date={m.joined_at} />
        </span>
      ),
    },
  ];

  const projectColumns: SignalDataTableColumn<WorkspaceProject>[] = [
    {
      key: "project",
      header: "Project",
      sortable: true,
      sortValue: (p) => p.name,
      renderCell: (p) => (
        <div className="flex flex-col">
          <span className="font-semibold text-(--t-1)">{p.name}</span>
          <span className="font-(family-name:--mono) text-[10.5px] text-(--t-3)">ID: {p.id}</span>
        </div>
      ),
    },
    {
      key: "domain",
      header: "Domain",
      renderCell: (p) => <span className="text-(--t-2)">{p.domain_url || "-"}</span>,
    },
    {
      key: "created",
      header: "Created",
      sortable: true,
      sortValue: (p) => p.created_at,
      renderCell: (p) => (
        <span className="text-(--t-2)">
          <ClientSafeDate date={p.created_at} />
        </span>
      ),
    },
  ];

  const auditColumns: SignalDataTableColumn<AuditHistoryItem>[] = [
    {
      key: "url",
      header: "URL",
      renderCell: (a) => <span className="block max-w-[300px] truncate text-(--t-1)">{a.url}</span>,
    },
    {
      key: "type",
      header: "Type",
      renderCell: (a) => <span className={CHIP_NEUTRAL}>{a.audit_type ?? "-"}</span>,
    },
    {
      key: "project",
      header: "Project",
      renderCell: (a) => <span className="text-(--t-2)">{a.project_name ?? "-"}</span>,
    },
    {
      key: "scores",
      header: "Scores",
      renderCell: (a) => (
        <div className="flex gap-2 text-[10.5px] font-semibold">
          {a.geo_score != null && (
            <span className="text-(--good)">AI visibility {Math.round(a.geo_score)}</span>
          )}
          {a.seo_score != null && (
            <span className="text-(--t-2)">SEO {Math.round(a.seo_score)}</span>
          )}
          {a.aeo_score != null && (
            <span className="text-(--purple)">AI answers {Math.round(a.aeo_score)}</span>
          )}
        </div>
      ),
    },
    {
      key: "date",
      header: "Date",
      sortable: true,
      sortValue: (a) => a.created_at ?? "",
      renderCell: (a) => (
        <span className="text-(--t-2)">
          {a.created_at ? <ClientSafeDate date={a.created_at} /> : "-"}
        </span>
      ),
    },
  ];

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions:
        isAdmin && workspace ? (
          <>
            <Button variant="danger" size="sm" onClick={() => setDeleteOpen(true)}>
              <X size={14} />
              <span className="max-sm:hidden">Delete</span>
            </Button>
            <Button variant="primary" size="sm" onClick={() => setEditOpen(true)}>
              <Pencil size={14} />
              <span className="max-sm:hidden">Edit</span>
            </Button>
          </>
        ) : null,
    });
    return () => setHeader(null);
  }, [isAdmin, setHeader, workspace]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24">
        <p className={MONO_META}>Loading workspace...</p>
      </div>
    );
  }

  if (error || !workspace) {
    return (
      <>
        <button
          onClick={() => router.push("/admin/workspaces")}
          className="flex items-center gap-2 font-(family-name:--mono) text-[11.5px] tracking-[0.06em] text-(--t-3) transition-colors hover:text-(--t-1)"
        >
          <ArrowLeft size={14} /> Back to workspaces
        </button>
        <Alert variant="destructive">
          <AlertDescription>{error || "Workspace not found."}</AlertDescription>
        </Alert>
      </>
    );
  }

  const planStyle = PLAN_BADGE_STYLES[workspace.plan_name] ?? PLAN_BADGE_STYLES.plan_standard;
  const planLabel =
    PLAN_DISPLAY_NAMES[workspace.plan_name] ?? workspace.plan_name.replace(/_/g, " ");

  return (
    <>
      {/* Back link */}
      <button
        onClick={() => router.push("/admin/workspaces")}
        className="flex items-center gap-2 font-(family-name:--mono) text-[11.5px] tracking-[0.06em] text-(--t-3) transition-colors hover:text-(--t-1)"
      >
        <ArrowLeft size={14} /> Back to workspaces
      </button>

      {/* Header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <DashboardPageIntro icon={Building2} title={workspace.name}>
          <span className="inline-flex flex-wrap items-center gap-3">
            <span className={planStyle}>
              <Crown size={10} />
              {planLabel}
            </span>
            <span>Owner: {workspace.owner_email}</span>
            <span>
              Created: <ClientSafeDate date={workspace.created_at} />
            </span>
          </span>
        </DashboardPageIntro>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Members" value={workspace.usage_summary.member_count} />
        <StatCard label="Projects" value={workspace.usage_summary.projects_count} />
        <StatCard label="Total assessments" value={workspace.usage_summary.total_audits} />
        <StatCard label="Audits this month" value={workspace.usage_summary.audits_this_month} />
      </div>

      {/* Tabs */}
      <SignalTabs tabs={TABS} activeId={activeTab} onChange={(id) => setActiveTab(id as TabKey)} />

      {/* Tab content */}
      {activeTab === "members" && (
        <SignalDataTable
          columns={memberColumns}
          rows={workspace.members}
          rowKey={(m) => m.user_id}
          emptyLabel="No members found."
          metaLabel={`${workspace.members.length} members`}
        />
      )}

      {activeTab === "projects" && (
        <SignalDataTable
          columns={projectColumns}
          rows={workspace.projects}
          rowKey={(p) => p.id}
          emptyLabel="No projects found."
          metaLabel={`${workspace.projects.length} projects`}
        />
      )}

      {activeTab === "audits" && (
        <SignalDataTable
          columns={auditColumns}
          rows={auditItems}
          rowKey={(a) => a.id}
          emptyLabel={auditLoading ? "Loading assessment history..." : "No assessments found."}
          metaLabel={`${auditTotal} assessments`}
          pageSize={auditPageSize}
          footer={
            <>
              <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
                Page {auditPage} of {auditTotalPages}
              </span>
              <nav className="ms-auto inline-flex items-center gap-1" aria-label="Pagination">
                <button
                  type="button"
                  onClick={() => setAuditPage((p) => Math.max(1, p - 1))}
                  disabled={auditPage <= 1}
                  aria-label="Previous page"
                  className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => setAuditPage((p) => Math.min(auditTotalPages, p + 1))}
                  disabled={auditPage >= auditTotalPages}
                  aria-label="Next page"
                  className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
                >
                  <ChevronRight size={14} />
                </button>
              </nav>
            </>
          }
        />
      )}

      {/* Edit modal */}
      <EditNameModal
        isOpen={editOpen}
        currentName={workspace.name}
        onClose={() => setEditOpen(false)}
        onSave={handleSaveName}
        isSaving={editSaving}
      />

      {/* Delete modal */}
      {workspace && (
        <DeleteWorkspaceModal
          isOpen={deleteOpen}
          workspace={workspace}
          workspacesList={workspacesList}
          onClose={() => setDeleteOpen(false)}
          onConfirm={handleDeleteWorkspace}
          isDeleting={deleteSaving}
        />
      )}
    </>
  );
}
