"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Eye,
  Pencil,
  Trash2,
  UserMinus,
  Coins,
  Search,
  RefreshCcw,
  ChevronRight,
  ChevronLeft,
  UserPlus,
  Shield,
  ShieldCheck,
  Activity,
  Crown,
  X,
  User,
  AlertTriangle,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { ClientSafeDate, formatDate, formatDateTime } from "@/lib/dateFormat";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { toast } from "sonner";
import { PLAN_DISPLAY_NAMES, PUBLIC_PLAN_OPTIONS, resolvePlanType } from "@/lib/planCapabilities";

type AdminUser = {
  id: number;
  email: string;
  role: string;
  credits: number;
  notifications_enabled: boolean;
  plan: string;
  subscription_status: string | null;
  audit_count: number;
};

type AdminUsersResponse = {
  users: AdminUser[];
  page: number;
  page_size: number;
  total: number;
};

type AdminUserAuditSummary = {
  total: number;
  last_audit_at: string | null;
  last_audit_url: string | null;
};

type AdminUserSubscriptionSummary = {
  plan: string;
  status: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean | null;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
};

type AdminUserDetailResponse = {
  user: AdminUser;
  audit_summary: AdminUserAuditSummary;
  subscription_summary: AdminUserSubscriptionSummary;
};

type ModalType = "details" | "edit" | "credits" | "delete" | "invite" | null;

type AdminInviteUserResponse = {
  user_id: number;
  email: string;
  role: string;
  invited: boolean;
  email_queued: boolean;
  invitation_url: string | null;
};

type AdminModalProps = {
  title: string;
  description?: string;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
};

const PLAN_OPTIONS = PUBLIC_PLAN_OPTIONS;

const SUPPORTED_PLAN_VALUES: ReadonlySet<string> = new Set(
  PLAN_OPTIONS.map((option) => option.value)
);

const normalizePlanValue = (plan: string | null | undefined): string => {
  const canonicalPlan = resolvePlanType(plan);
  return canonicalPlan && SUPPORTED_PLAN_VALUES.has(canonicalPlan) ? canonicalPlan : "";
};

const isSupportedPlanValue = (plan: string): boolean => SUPPORTED_PLAN_VALUES.has(plan);

const formatPlanLabel = (plan: string | null | undefined): string => {
  const canonicalPlan = resolvePlanType(plan);
  return canonicalPlan ? PLAN_DISPLAY_NAMES[canonicalPlan] : plan || "Starter";
};

const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const WTEXTAREA = `${WINPUT} h-auto min-h-[76px] resize-y py-[11px]`;
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const ACTION_ICON =
  "flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--t-2) transition-colors hover:border-(--purple) hover:text-(--purple) disabled:opacity-40";

const AdminModal = ({ title, description, open, onClose, children, footer }: AdminModalProps) => {
  const titleId = React.useId();
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      ariaLabelledby={titleId}
      panelClassName="px-0 pt-0 pb-0"
    >
      <div className="flex items-center justify-between border-b border-(--line) px-[22px] py-[18px]">
        <div>
          <h2
            id={titleId}
            className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)"
          >
            {title}
          </h2>
          {description && <p className={`${MONO_META} mt-1`}>{description}</p>}
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--t-2) transition-colors hover:text-(--t-1)"
        >
          <X size={16} />
        </button>
      </div>
      <div className="max-h-[70vh] overflow-y-auto px-[22px] py-5">{children}</div>
      {footer && <div className="border-t border-(--line) px-[22px] py-4">{footer}</div>}
    </Modal>
  );
};

export default function AdminUsersPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [totalUsers, setTotalUsers] = useState(0);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const [activeModal, setActiveModal] = useState<ModalType>(null);
  const [activeUser, setActiveUser] = useState<AdminUser | null>(null);
  const [userDetails, setUserDetails] = useState<AdminUserDetailResponse | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  const [editRole, setEditRole] = useState("user");
  const [editPlan, setEditPlan] = useState("");
  const [editNotifications, setEditNotifications] = useState(true);
  const [creditDelta, setCreditDelta] = useState(0);
  const [creditReason, setCreditReason] = useState("");

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState("user");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin data.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadUsers = useCallback(async () => {
    if (!isSignedIn) {
      return;
    }
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (query.trim()) {
        params.set("query", query.trim());
      }
      const response = await fetch(`/api/admin/users?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load users.");
      }
      const payload = (await response.json()) as AdminUsersResponse;
      setUsers(payload.users);
      setTotalUsers(payload.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load users.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn, page, pageSize, query]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    setPage(1);
  }, [query, pageSize]);

  const loadUserDetails = useCallback(
    async (userId: number): Promise<AdminUserDetailResponse> => {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/users/${userId}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load user details.");
      }
      return (await response.json()) as AdminUserDetailResponse;
    },
    [getAuthHeaders]
  );

  useEffect(() => {
    if (activeModal === "edit" && activeUser) {
      setEditRole(activeUser.role);
      setEditNotifications(activeUser.notifications_enabled);
      const detailsPlan =
        userDetails && userDetails.user.id === activeUser.id
          ? userDetails.subscription_summary.plan
          : undefined;
      setEditPlan(normalizePlanValue(detailsPlan ?? activeUser.plan));
    }
    if (activeModal === "credits") {
      setCreditDelta(0);
      setCreditReason("");
    }
    if (activeModal === "invite") {
      setInviteEmail("");
      setInviteName("");
      setInviteRole("user");
    }
    if (activeModal !== "details") {
      setUserDetails(null);
    }
    setActionError("");
  }, [activeModal, activeUser, userDetails]);

  useEffect(() => {
    const fetchDetails = async () => {
      if (!activeUser || activeModal !== "details") {
        return;
      }
      setDetailsLoading(true);
      try {
        const payload = await loadUserDetails(activeUser.id);
        setUserDetails(payload);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Unable to load user details.");
      } finally {
        setDetailsLoading(false);
      }
    };
    fetchDetails();
  }, [activeModal, activeUser, loadUserDetails]);

  const isEditPlanValid = editPlan === "" || isSupportedPlanValue(editPlan);

  const controlsDisabled = !isAdmin || isLoading || isGuardLoading || actionLoading;

  const closeModal = () => {
    if (!actionLoading) {
      setActiveModal(null);
      setActiveUser(null);
    }
  };

  const openModal = (type: ModalType, user: AdminUser) => {
    setActiveModal(type);
    setActiveUser(user);
  };

  const openInviteModal = () => {
    setActiveUser(null);
    setActiveModal("invite");
  };

  const totalPages = Math.max(1, Math.ceil(totalUsers / pageSize));

  const detailsRows = useMemo(() => {
    const user = userDetails?.user ?? activeUser;
    if (!user) {
      return [];
    }
    const auditSummary = userDetails?.audit_summary;
    const subscriptionSummary = userDetails?.subscription_summary;
    return [
      { label: "Email", value: user.email },
      { label: "Role", value: user.role },
      { label: "Plan", value: formatPlanLabel(subscriptionSummary?.plan ?? user.plan) },
      { label: "Credits", value: user.credits.toString() },
      {
        label: "Assessments",
        value: auditSummary ? auditSummary.total.toString() : user.audit_count.toString(),
      },
      {
        label: "Last audit",
        value: auditSummary?.last_audit_at ? formatDateTime(auditSummary.last_audit_at) : "-",
      },
      {
        label: "Subscription status",
        value: subscriptionSummary?.status ?? user.subscription_status ?? "-",
      },
      {
        label: "Renews on",
        value: subscriptionSummary?.current_period_end
          ? formatDate(subscriptionSummary.current_period_end)
          : "-",
      },
      {
        label: "Notifications",
        value: user.notifications_enabled ? "Enabled" : "Disabled",
      },
    ];
  }, [activeUser, userDetails]);

  const handleUpdateUser = async () => {
    if (!activeUser) {
      return;
    }
    if (!isEditPlanValid) {
      setActionError("Select a valid package before saving.");
      return;
    }
    setActionLoading(true);
    setActionError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/users/${activeUser.id}`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          role: editRole,
          notifications_enabled: editNotifications,
          ...(editPlan ? { plan_type: editPlan } : {}),
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to update user.");
      }
      const payload = (await response.json()) as { user?: AdminUser };
      if (payload.user) {
        setActiveUser(payload.user);
      }
      await loadUsers();
      const refreshedDetails = await loadUserDetails(activeUser.id);
      setUserDetails(refreshedDetails);
      closeModal();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unable to update user.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreditAdjustment = async () => {
    if (!activeUser) {
      return;
    }
    if (creditDelta === 0) {
      setActionError("Enter a non-zero credit adjustment.");
      return;
    }
    if (!creditReason.trim()) {
      setActionError("Provide a reason for the credit adjustment.");
      return;
    }
    setActionLoading(true);
    setActionError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/users/${activeUser.id}/credits`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ delta: creditDelta, reason: creditReason.trim() }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to update credits.");
      }
      await loadUsers();
      closeModal();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unable to update credits.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteUser = async () => {
    if (!activeUser) {
      return;
    }
    setActionLoading(true);
    setActionError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/users/${activeUser.id}`, {
        method: "DELETE",
        headers,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to delete user.");
      }
      await loadUsers();
      closeModal();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unable to delete user.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleInviteUser = async () => {
    const trimmedEmail = inviteEmail.trim();
    if (!trimmedEmail) {
      setActionError("Email address is required.");
      return;
    }
    setActionLoading(true);
    setActionError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/users/invite`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          email: trimmedEmail,
          name: inviteName.trim() || null,
          role: inviteRole,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        if (response.status === 409) {
          setActionError(payload?.detail ?? "A user with this email already exists.");
          return;
        }
        throw new Error(payload?.detail ?? "Unable to invite user.");
      }
      const payload = (await response.json()) as AdminInviteUserResponse;
      toast.success(
        payload.email_queued
          ? `Invitation email sent to ${payload.email}.`
          : `User ${payload.email} created. Email delivery is disabled, so share the setup link with them manually.`
      );
      await loadUsers();
      closeModal();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to invite user.");
    } finally {
      setActionLoading(false);
    }
  };

  const columns: SignalDataTableColumn<AdminUser>[] = [
    {
      key: "user",
      header: "User",
      sortable: true,
      sortValue: (u) => u.email,
      renderCell: (u) => (
        <div className="flex flex-col">
          <span className="font-semibold text-(--t-1)">{u.email}</span>
          <span className="font-(family-name:--mono) text-[10.5px] text-(--t-3)">UID: {u.id}</span>
        </div>
      ),
    },
    {
      key: "role",
      header: "Role",
      renderCell: (u) => (
        <span
          className={`${CHIP} ${
            u.role === "admin"
              ? "text-(--purple) bg-(--purple-s)"
              : u.role === "moderator"
                ? "text-(--warn) bg-(--warn-s)"
                : "text-(--t-2) bg-(--line-2)"
          }`}
        >
          {u.role === "admin" ? (
            <Crown size={10} />
          ) : u.role === "moderator" ? (
            <ShieldCheck size={10} />
          ) : (
            <User size={10} />
          )}
          {u.role}
        </span>
      ),
    },
    {
      key: "plan",
      header: "Subscription plan",
      renderCell: (u) => (
        <span className={`${CHIP} text-(--t-2) bg-(--line-2)`}>{formatPlanLabel(u.plan)}</span>
      ),
    },
    {
      key: "credits",
      header: "Credits",
      sortable: true,
      sortValue: (u) => u.credits,
      renderCell: (u) => <span className="font-semibold text-(--purple)">{u.credits}</span>,
    },
    {
      key: "audits",
      header: "Audits run",
      sortable: true,
      sortValue: (u) => u.audit_count,
      renderCell: (u) => (
        <div className="flex items-center gap-1.5 text-(--t-2)">
          <Activity size={14} className="text-(--t-3)" />
          <span className="font-semibold">{u.audit_count}</span>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      renderCell: (u) => (
        <span
          className={`${CHIP} ${
            u.subscription_status === "active"
              ? "text-(--good) bg-(--good-s)"
              : "text-(--t-3) bg-(--line-2)"
          }`}
        >
          {u.subscription_status ?? "OFFLINE"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      renderCell: (u) => (
        <div className="flex justify-end gap-1.5">
          <button
            onClick={() => openModal("details", u)}
            disabled={controlsDisabled}
            title="View Details"
            className={ACTION_ICON}
          >
            <Eye size={14} />
          </button>
          <button
            onClick={() => openModal("edit", u)}
            disabled={controlsDisabled}
            title="Edit User"
            className={ACTION_ICON}
          >
            <Pencil size={14} />
          </button>
          <button
            onClick={() => openModal("credits", u)}
            disabled={controlsDisabled}
            title="Adjust Credits"
            className={ACTION_ICON}
          >
            <Coins size={14} />
          </button>
          <button
            onClick={() => openModal("delete", u)}
            disabled={controlsDisabled}
            title="Delete User"
            className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--bad) transition-colors hover:bg-(--bad-s) disabled:opacity-40"
          >
            <Trash2 size={14} />
          </button>
        </div>
      ),
    },
  ];

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <Button variant="primary" size="sm" disabled={controlsDisabled} onClick={openInviteModal}>
          <UserPlus size={14} />
          <span className="max-sm:hidden">Invite user</span>
        </Button>
      ),
    });
    return () => setHeader(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- openInviteModal is a stable setter pair
  }, [controlsDisabled, setHeader]);

  const actionErrorNode = actionError ? (
    <p className="flex items-center gap-2 text-xs font-medium text-(--bad)">
      <Shield size={12} />
      {actionError}
    </p>
  ) : null;

  return (
    <>
      <DashboardPageIntro icon={Shield} title="User management">
        Manage user accounts, roles, and platform access.
      </DashboardPageIntro>

      {error ? (
        <Alert variant="destructive">
          <Shield />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <SignalDataTable
        columns={columns}
        rows={users}
        rowKey={(u) => u.id}
        emptyLabel={isLoading ? "Loading users..." : "No users found."}
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
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search email, external ID, or role..."
                aria-label="Search users"
                className="field-focus-ring h-8 w-full rounded-(--r-sm) border-0 bg-[#EEF1F6] pl-8 pr-2.5 text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c9cef7]"
              />
            </div>
            <NativeSelect
              variant="auth"
              value={pageSize}
              onChange={(event) => setPageSize(Number(event.target.value))}
              className="h-8 w-auto text-[12.5px]"
              aria-label="Rows per page"
            >
              {[10, 25, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size} Rows
                </option>
              ))}
            </NativeSelect>
          </>
        }
        metaLabel={`${users.length} / ${totalUsers} users`}
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
                disabled={page <= 1 || controlsDisabled}
                aria-label="Previous page"
                className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
              >
                <ChevronLeft size={14} />
              </button>
              <button
                type="button"
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
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

      <AdminModal
        title="User details"
        description={activeUser ? `Account overview for ${activeUser.email}` : undefined}
        open={activeModal === "details" && Boolean(activeUser)}
        onClose={closeModal}
        footer={
          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={closeModal}>
              Close
            </Button>
          </div>
        }
      >
        {detailsLoading ? (
          <div className="flex flex-col items-center gap-3 py-8">
            <p className={MONO_META}>Loading user details...</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {detailsRows.map((row) => (
              <div
                key={row.label}
                className="rounded-(--r-md) border-0 bg-[#EEF1F6] p-3"
              >
                <p className={`${MICRO_LABEL} mb-1`}>{row.label}</p>
                <p className="text-xs font-semibold wrap-break-word text-(--t-1)">
                  {row.label.toLowerCase().includes("date") ||
                  row.label.toLowerCase().includes("at") ||
                  row.label.toLowerCase().includes("on") ? (
                    <ClientSafeDate date={row.value} />
                  ) : (
                    row.value
                  )}
                </p>
              </div>
            ))}
          </div>
        )}
      </AdminModal>

      <AdminModal
        title="Edit user"
        description={activeUser ? `Update account settings for ${activeUser.email}` : undefined}
        open={activeModal === "edit" && Boolean(activeUser)}
        onClose={closeModal}
        footer={
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">{actionErrorNode}</div>
            <div className="flex gap-3">
              <Button variant="ghost" onClick={closeModal} disabled={actionLoading}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleUpdateUser}
                disabled={actionLoading || !isEditPlanValid}
              >
                {actionLoading ? "Saving..." : "Save changes"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className={FIELD_LABEL}>Role</label>
              <NativeSelect
                variant="auth"
                value={editRole}
                onChange={(event) => setEditRole(event.target.value)}
              >
                <option value="user">User</option>
                <option value="moderator">Moderator</option>
                <option value="admin">Admin</option>
              </NativeSelect>
            </div>

            <div>
              <label className={FIELD_LABEL}>Subscription plan</label>
              <NativeSelect
                variant="auth"
                value={editPlan}
                onChange={(event) => setEditPlan(event.target.value)}
              >
                <option value="">Keep current package ({formatPlanLabel(activeUser?.plan)})</option>
                {PLAN_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-(--r-md) bg-(--purple-s) text-(--purple)">
                <RefreshCcw size={16} />
              </div>
              <div>
                <p className="text-[13.5px] font-semibold text-(--t-1)">Email notifications</p>
                <p className="max-w-[240px] text-xs text-(--t-3)">Product updates and alerts.</p>
              </div>
            </div>
            <ToggleSwitch
              checked={editNotifications}
              onChange={setEditNotifications}
              aria-label="Email notifications"
            />
          </div>

          {!isEditPlanValid && (
            <Alert variant="warning">
              <AlertTriangle />
              <AlertDescription>Plan selection required to save changes.</AlertDescription>
            </Alert>
          )}
        </div>
      </AdminModal>

      <AdminModal
        title="Adjust credits"
        description={activeUser ? `Credit adjustment for ${activeUser.email}` : undefined}
        open={activeModal === "credits" && Boolean(activeUser)}
        onClose={closeModal}
        footer={
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">{actionErrorNode}</div>
            <div className="flex gap-3">
              <Button variant="ghost" onClick={closeModal} disabled={actionLoading}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleCreditAdjustment} disabled={actionLoading}>
                {actionLoading ? "Updating..." : "Update balance"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-5">
          <div className="flex items-center justify-between rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4">
            <div>
              <p className={MICRO_LABEL}>Current balance</p>
              <p className="mt-1 font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
                {activeUser?.credits ?? 0}{" "}
                <span className={`${MICRO_LABEL} text-(--purple)`}>Credits</span>
              </p>
            </div>
            <div className="flex h-11 w-11 items-center justify-center rounded-(--r-md) bg-(--purple-s) text-(--purple)">
              <Coins size={20} />
            </div>
          </div>

          <div>
            <label className={FIELD_LABEL}>Adjustment amount</label>
            <input
              type="number"
              value={creditDelta}
              onChange={(event) => setCreditDelta(Number(event.target.value))}
              placeholder="e.g. 100 or -50"
              className={WINPUT}
            />
          </div>

          <div>
            <label className={FIELD_LABEL}>Reason</label>
            <textarea
              value={creditReason}
              onChange={(event) => setCreditReason(event.target.value)}
              className={WTEXTAREA}
              rows={3}
              placeholder="Internal note for this adjustment..."
            />
          </div>
        </div>
      </AdminModal>

      <AdminModal
        title="Delete user"
        description={activeUser ? `Permanent deletion: ${activeUser.email}` : undefined}
        open={activeModal === "delete" && Boolean(activeUser)}
        onClose={closeModal}
        footer={
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">{actionErrorNode}</div>
            <div className="flex gap-3">
              <Button variant="ghost" onClick={closeModal} disabled={actionLoading}>
                Cancel
              </Button>
              <Button variant="danger" onClick={handleDeleteUser} disabled={actionLoading}>
                {actionLoading ? "Deleting..." : "Confirm delete"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-4">
          <Alert variant="destructive">
            <UserMinus />
            <AlertDescription>
              <p className="font-semibold text-(--t-1)">Irreversible action</p>
              <p>
                This action will permanently remove this user, their audits, subscriptions, and
                billing records from the database.
              </p>
            </AlertDescription>
          </Alert>
          {actionLoading && <p className={`${MONO_META} text-center`}>Deleting user...</p>}
        </div>
      </AdminModal>

      <AdminModal
        title="Invite user"
        description="Create an account and email a setup link"
        open={activeModal === "invite"}
        onClose={closeModal}
        footer={
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">{actionErrorNode}</div>
            <div className="flex gap-3">
              <Button variant="ghost" onClick={closeModal} disabled={actionLoading}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleInviteUser} disabled={actionLoading}>
                {actionLoading ? "Sending..." : "Send invite"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-5">
          <div>
            <label className={FIELD_LABEL}>Email address</label>
            <input
              type="email"
              value={inviteEmail}
              onChange={(event) => setInviteEmail(event.target.value)}
              placeholder="name@company.com"
              className={WINPUT}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className={FIELD_LABEL}>Name (optional)</label>
              <input
                type="text"
                value={inviteName}
                onChange={(event) => setInviteName(event.target.value)}
                placeholder="Jane Doe"
                className={WINPUT}
              />
            </div>

            <div>
              <label className={FIELD_LABEL}>Role</label>
              <NativeSelect
                variant="auth"
                value={inviteRole}
                onChange={(event) => setInviteRole(event.target.value)}
              >
                <option value="user">User</option>
                <option value="moderator">Moderator</option>
                <option value="admin">Admin</option>
              </NativeSelect>
            </div>
          </div>

          <div className="rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-3">
            <p className="text-xs text-(--t-3)">
              A new account is created with a random password. We will email a link to set their own
              password.
            </p>
          </div>
        </div>
      </AdminModal>
    </>
  );
}
