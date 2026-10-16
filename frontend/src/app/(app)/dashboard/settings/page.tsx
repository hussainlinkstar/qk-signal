"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  FolderOpen,
  Loader2,
  Palette,
  Settings2,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/components/auth/custom-auth";
import { workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import WorkspacePageFrame from "@/components/dashboard/WorkspacePageFrame";
import SignalTabs, { SignalTabPanel } from "@/components/signal/SignalTabs";
import RoleModeSwitcher from "@/components/app/RoleModeSwitcher";
import ApiKeysSection from "@/components/settings/ApiKeysSection";
import WorkspaceWhiteLabelSection from "@/components/settings/WorkspaceWhiteLabelSection";
import { WorkspaceCostBreakdownSection } from "@/components/settings/WorkspaceCostBreakdownSection";
import { resolveServedCapability } from "@/lib/planCapabilities";
import { useBillingSettings } from "@/hooks/useBillingSettings";
import { BILLING_EMAIL } from "@/lib/contact";
import {
  addWorkspaceMember,
  deleteWorkspace,
  fetchCurrentWorkspace,
  fetchUserWorkspaces,
  fetchWorkspaceMembers,
  fetchWorkspaceProjects,
  fetchWorkspaceCostBreakdown,
  inviteWorkspaceClient,
  removeWorkspaceMember,
  type InternalWorkspaceRole,
  type WorkspaceCostBreakdown,
  type WorkspaceMemberSummary,
  type WorkspaceProjectSummary,
  type WorkspaceSummary,
  updateCurrentWorkspace,
  updateWorkspaceMemberRole,
} from "@/services/workspaceService";
import { CreateWorkspaceModal } from "@/components/app/CreateWorkspaceModal";
import InviteToMultipleWorkspacesModal from "@/components/app/InviteToMultipleWorkspacesModal";
import { Skel, SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";
import { getActiveWorkspaceId, setActiveWorkspaceId } from "@/components/app/WorkspaceSwitcher";

const INTERNAL_ROLE_OPTIONS: InternalWorkspaceRole[] = ["ADMIN", "MANAGER", "EDITOR", "VIEWER"];

const resolveErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
};

const stripDomainProtocol = (value: string | null) =>
  value ? value.replace(/^https?:\/\//i, "").replace(/\/$/, "") : "Pending domain";

const formatCreatedAt = (value: string | null) => {
  if (!value) {
    return "recently";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "recently";
  }

  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

// The five tabs of the approved Workspace Settings page, in its order
// (SIGV2-1039). White-Label used to be absent entirely.
const SETTINGS_SECTIONS = [
  {
    id: "workspace-overview",
    label: "General",
    icon: Settings2,
    description: "Workspace identity and multi-workspace management",
  },
  {
    id: "workspace-team",
    label: "Team",
    icon: Users,
    description: "Internal team member access and roles",
  },
  {
    id: "workspace-client-access",
    label: "Client Access",
    icon: FolderOpen,
    description: "Client portal invitations and project assignments",
  },
  {
    id: "workspace-white-label",
    label: "White-Label",
    icon: Palette,
    description: "Brand assets, accent colors, email sender and custom domain",
  },
  {
    id: "workspace-developer",
    label: "Developer",
    icon: Sparkles,
    description: "API keys and usage cost breakdown",
    requiredCapability: "api_access" as const,
  },
] as const;

// "Arranged with our team" needs a route to the team. The billing inbox is the
// one that already exists and is already the sales intake address used by
// BillingSalesContactCard, so this adds no new surface.
const CONTACT_SALES_HREF = `mailto:${BILLING_EMAIL}?subject=${encodeURIComponent(
  "Multiple workspaces enquiry"
)}`;

type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number]["id"];

const sortMembers = (members: WorkspaceMemberSummary[]) =>
  [...members].sort((left, right) => {
    const ownerDelta = Number(right.is_owner) - Number(left.is_owner);
    if (ownerDelta !== 0) {
      return ownerDelta;
    }

    const portalDelta =
      Number(left.role === "CLIENT_READONLY") - Number(right.role === "CLIENT_READONLY");
    if (portalDelta !== 0) {
      return portalDelta;
    }

    return left.email.localeCompare(right.email);
  });

function WorkspaceSettingsPage() {
  const { getToken, isLoading: authLoading, isSignedIn, user } = useAuth();
  // Entitlement comes from what the API serves on /api/billing/plans
  // (`plans[].capabilities` straight out of the backend CAPABILITY_MATRIX,
  // plus `current_plan`), never from a frontend plan table. The table in
  // lib/planCapabilities.ts is the pre-payload fallback only: it disagreed
  // with the backend on exactly these two keys, which is how an entitled
  // Executive customer ended up locked out of both.
  const { billingOverview } = useBillingSettings();
  const canMultiWorkspace = useMemo(
    () =>
      resolveServedCapability(
        billingOverview,
        "has_multi_workspace_federation",
        user?.subscription_plan
      ),
    [billingOverview, user?.subscription_plan]
  );
  const canWhiteLabel = useMemo(
    () => resolveServedCapability(billingOverview, "has_white_label", user?.subscription_plan),
    [billingOverview, user?.subscription_plan]
  );
  const visibleSections = SETTINGS_SECTIONS;

  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [allWorkspaces, setAllWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [showCreateWorkspaceModal, setShowCreateWorkspaceModal] = useState(false);
  const [showMultiInviteModal, setShowMultiInviteModal] = useState(false);
  const [busyWorkspaceId, setBusyWorkspaceId] = useState<number | null>(null);
  const [members, setMembers] = useState<WorkspaceMemberSummary[]>([]);
  const [projects, setProjects] = useState<WorkspaceProjectSummary[]>([]);
  const [costBreakdown, setCostBreakdown] = useState<WorkspaceCostBreakdown | null>(null);

  const [workspaceNameInput, setWorkspaceNameInput] = useState("");
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<InternalWorkspaceRole>("EDITOR");
  const [clientEmail, setClientEmail] = useState("");
  const [clientName, setClientName] = useState("");
  const [selectedClientProjectIds, setSelectedClientProjectIds] = useState<number[]>([]);
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("workspace-overview");

  const [isLoading, setIsLoading] = useState(true);
  // SIGV2-1311: why the page has nothing to show, when it has nothing.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoadingCostBreakdown, setIsLoadingCostBreakdown] = useState(true);
  const [isSavingWorkspace, setIsSavingWorkspace] = useState(false);
  const [isAddingMember, setIsAddingMember] = useState(false);
  const [isInvitingClient, setIsInvitingClient] = useState(false);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);

  const [costBreakdownError, setCostBreakdownError] = useState<string | null>(null);
  const [manualInvitationUrl, setManualInvitationUrl] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("Authentication token unavailable.");
    }

    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  const loadCostBreakdown = useCallback(async (workspaceId: number, headers: HeadersInit) => {
    setIsLoadingCostBreakdown(true);
    setCostBreakdownError(null);
    try {
      const payload = await fetchWorkspaceCostBreakdown(workspaceId, headers);
      setCostBreakdown(payload);
    } catch (err) {
      setCostBreakdown(null);
      setCostBreakdownError(resolveErrorMessage(err, "Failed to load workspace cost breakdown."));
    } finally {
      setIsLoadingCostBreakdown(false);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    if (authLoading || !isSignedIn) {
      if (!authLoading) {
        setIsLoading(false);
      }
      return;
    }

    setIsLoading(true);

    try {
      const headers = await getAuthHeaders();
      const workspacePayload = await fetchCurrentWorkspace(headers);
      const [membersPayload, projectsPayload] = await Promise.all([
        fetchWorkspaceMembers(headers),
        fetchWorkspaceProjects(headers),
      ]);

      setWorkspace(workspacePayload);
      setWorkspaceNameInput(workspacePayload.name);
      setMembers(sortMembers(membersPayload));
      setProjects([...projectsPayload].sort((left, right) => left.name.localeCompare(right.name)));
      await loadCostBreakdown(workspacePayload.id, headers);
      // Load all workspaces so the "My Workspaces" panel can display them.
      const allWs = await fetchUserWorkspaces(headers);
      setAllWorkspaces(allWs);
      setLoadError(null);
    } catch (err) {
      const message = resolveErrorMessage(err, "Failed to load workspace settings.");
      toast.error(message);
      // SIGV2-1311: a failed read is not an empty workspace.
      //
      // The whole load sits in one try, so a failure anywhere left `workspace`
      // null and `members` empty, and the page then rendered that as fact:
      // "Team Roster (0), No internal team members found", with no Invite
      // control, because `canManage` reads a role nobody had loaded. QA logged
      // it as a blocker, and the only signal that anything had gone wrong was
      // a toast that disappears.
      //
      // A workspace always has at least its owner, so a roster of zero is not
      // a reachable state. Holding the error lets the page say what happened
      // instead of asserting something impossible.
      setLoadError(message);
      setIsLoadingCostBreakdown(false);
    } finally {
      setIsLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, loadCostBreakdown]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  // Reset active section if it becomes hidden due to plan capabilities
  useEffect(() => {
    const visibleIds = visibleSections.map((s) => s.id);
    if (!visibleIds.includes(activeSection)) {
      setActiveSection(visibleIds[0] ?? "workspace-overview");
    }
  }, [activeSection, visibleSections]);

  const canManage =
    workspace?.role === "ADMIN" || workspace?.role === "MANAGER" || workspace?.role === "EDITOR";

  const handleDeleteWorkspace = useCallback(
    async (wsId: number) => {
      if (
        !confirm("Delete this workspace? All projects and data inside will be permanently removed.")
      )
        return;
      setBusyWorkspaceId(wsId);
      try {
        const headers = await getAuthHeaders();
        await deleteWorkspace(wsId, headers);
        // If the deleted workspace was active, switch to another one.
        const activeId = getActiveWorkspaceId();
        if (activeId === wsId) {
          const remaining = allWorkspaces.filter((w) => w.id !== wsId);
          if (remaining.length > 0) {
            setActiveWorkspaceId(remaining[0].id);
          }
          window.location.reload();
        } else {
          setAllWorkspaces((prev) => prev.filter((w) => w.id !== wsId));
        }
      } catch (err) {
        toast.error(resolveErrorMessage(err, "Failed to delete workspace."));
      } finally {
        setBusyWorkspaceId(null);
      }
    },
    [allWorkspaces, getAuthHeaders]
  );

  const internalMembers = useMemo(
    () => members.filter((member) => member.role !== "CLIENT_READONLY"),
    [members]
  );
  const clientMembers = useMemo(
    () => members.filter((member) => member.role === "CLIENT_READONLY"),
    [members]
  );

  const toggleClientProject = (projectId: number) => {
    setSelectedClientProjectIds((current) =>
      current.includes(projectId)
        ? current.filter((value) => value !== projectId)
        : [...current, projectId].sort((left, right) => left - right)
    );
  };

  const handleSaveName = async () => {
    if (!workspaceNameInput.trim()) {
      toast.error("Workspace name is required.");
      return;
    }

    setIsSavingWorkspace(true);

    try {
      const headers = await getAuthHeaders();
      const payload = await updateCurrentWorkspace({ name: workspaceNameInput.trim() }, headers);
      setWorkspace(payload);
      toast.success("Workspace settings saved.");
    } catch (err) {
      toast.error(resolveErrorMessage(err, "Unable to save workspace settings."));
    } finally {
      setIsSavingWorkspace(false);
    }
  };

  const handleAddMember = async () => {
    if (!memberEmail.trim()) {
      toast.error("Team member email is required.");
      return;
    }

    setIsAddingMember(true);

    try {
      const headers = await getAuthHeaders();
      const added = await addWorkspaceMember(memberEmail.trim(), memberRole, headers);
      setMembers((current) =>
        sortMembers([...current.filter((member) => member.user_id !== added.user_id), added])
      );
      setMemberEmail("");
      toast.success(`${added.email} added to the workspace.`);
      try {
        await fetch("/api/users/me/onboarding", {
          method: "PATCH",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({
            started: true,
            dismissed: false,
            add_completed_steps: ["invite_team_member"],
          }),
        });
      } catch {
        // non-critical, do not block the invite on onboarding tracking
      }
    } catch (err) {
      toast.error(resolveErrorMessage(err, "Failed to invite member."));
    } finally {
      setIsAddingMember(false);
    }
  };

  const handleInviteClient = async () => {
    if (!workspace) {
      toast.error("Workspace context is unavailable.");
      return;
    }
    if (!clientEmail.trim()) {
      toast.error("Client email is required.");
      return;
    }
    if (selectedClientProjectIds.length === 0) {
      toast.error("Select at least one project for client portal access.");
      return;
    }

    setIsInvitingClient(true);

    try {
      const headers = await getAuthHeaders();
      const payload = await inviteWorkspaceClient(
        workspace.id,
        {
          email: clientEmail.trim(),
          name: clientName.trim() || null,
          project_ids: selectedClientProjectIds,
        },
        headers
      );

      setMembers((current) =>
        sortMembers([
          ...current.filter((member) => member.user_id !== payload.user_id),
          {
            user_id: payload.user_id,
            email: payload.email,
            role: payload.role,
            is_owner: false,
            created_at: payload.created_at,
          },
        ])
      );
      setClientEmail("");
      setClientName("");
      setSelectedClientProjectIds([]);
      setManualInvitationUrl(payload.invitation_url);
      toast.success(
        payload.email_queued
          ? payload.invited
            ? `${payload.email} invited to the client portal.`
            : `Client portal access updated for ${payload.email}.`
          : `Client access was assigned for ${payload.email}, but the invitation email was not queued. Configure email delivery before asking the client to sign in.`
      );
    } catch (err) {
      toast.error(resolveErrorMessage(err, "Failed to invite client."));
    } finally {
      setIsInvitingClient(false);
    }
  };

  const handleRoleUpdate = async (userId: number, role: InternalWorkspaceRole) => {
    setBusyUserId(userId);

    try {
      const headers = await getAuthHeaders();
      const updated = await updateWorkspaceMemberRole(userId, role, headers);
      setMembers((current) =>
        sortMembers(current.map((member) => (member.user_id === userId ? updated : member)))
      );
      toast.success("Member role updated.");
    } catch (err) {
      toast.error(resolveErrorMessage(err, "Permission denied."));
    } finally {
      setBusyUserId(null);
    }
  };

  const handleRemoveMember = async (userId: number) => {
    setBusyUserId(userId);

    try {
      const headers = await getAuthHeaders();
      await removeWorkspaceMember(userId, headers);
      setMembers((current) => current.filter((member) => member.user_id !== userId));
      toast.success("Workspace access removed.");
    } catch (err) {
      toast.error(resolveErrorMessage(err, "Unable to remove workspace access."));
    } finally {
      setBusyUserId(null);
    }
  };

  if (isLoading) {
    return (
      <div role="status" className="flex flex-col gap-[18px]">
        <SkelPagehead />
        <Skel className="h-[34px] w-[280px] rounded-[9px]" />
        <SkelCard className="h-[220px]" />
        <SkelCard className="h-[160px]" />
        <span className="sr-only">Loading</span>
      </div>
    );
  }

  // SIGV2-1311: the settings could not be read, so the page says that rather
  // than drawing an empty workspace the customer cannot act on.
  if (loadError !== null && workspace === null) {
    return (
      <div
        role="alert"
        className="rounded-[22px] border-0 bg-white px-[22px] py-6"
      >
        <h2 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
          Workspace settings could not be loaded
        </h2>
        <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">{loadError}</p>
        <button
          type="button"
          onClick={() => void loadSettings()}
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <WorkspacePageFrame backHref="/dashboard" backLabel="Back to Workspace Overview">
      <div className="flex flex-col gap-[22px]">
        <DashboardPageIntro title="Workspace Settings">
          Manage workspace identity, team access, client portal, and white-label configuration.
        </DashboardPageIntro>

        {/* ── Tab Navigation ── */}
        <SignalTabs<SettingsSectionId>
          tabs={visibleSections.map((section) => ({
            id: section.id,
            label: section.label,
            count:
              section.id === "workspace-team"
                ? internalMembers.length
                : section.id === "workspace-client-access"
                  ? clientMembers.length
                  : undefined,
          }))}
          activeId={activeSection}
          onChange={setActiveSection}
        />

        <SignalTabPanel id={activeSection} activeId={activeSection}>
          {/* ── General / Overview Panel ── */}
          {activeSection === "workspace-overview" && (
            <div className="flex flex-col gap-[22px]">
              <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
                <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                  Workspace Identity
                </h3>
                <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
                  The display name for this workspace across the dashboard and client-facing
                  surfaces.
                </p>
                <div className="flex items-end gap-3 max-md:flex-col max-md:items-stretch">
                  <div className="mb-0 flex-1">
                    <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      Workspace name
                    </span>
                    <input
                      className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
                      type="text"
                      value={workspaceNameInput}
                      onChange={(event) => setWorkspaceNameInput(event.target.value)}
                      disabled={!canManage}
                    />
                  </div>
                  <button
                    type="button"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                    onClick={handleSaveName}
                    disabled={!canManage || !workspaceNameInput.trim() || isSavingWorkspace}
                  >
                    {isSavingWorkspace ? "Saving…" : "Save"}
                  </button>
                </div>
                <div className="mt-[22px] mb-4 last:mb-0">
                  <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                    Role mode
                  </span>
                  <p className="mb-2.5 text-[12px] text-(--t-3)">
                    Tailor the dashboard sections to how you work.
                  </p>
                  <RoleModeSwitcher />
                </div>
                {/* The connections page lives at /dashboard/connections and had
                    no way in from the UI (SIGV2-1265): no settings link and no
                    sidebar entry, so only the OAuth callback redirect or a
                    typed URL reached it. The panels stay on their own route
                    rather than being embedded here, which
                    styles/signal-mobile-reflow.test.ts asserts on purpose. */}
                <div className="mt-[22px] border-t border-t-(--line-2) pt-3.5">
                  <Link
                    href="/dashboard/connections"
                    className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-(--brand) hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--purple) max-md:min-h-11"
                  >
                    Manage workspace connections
                  </Link>
                </div>
              </div>

              <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
                <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                  My Workspaces
                </h3>
                <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
                  {canMultiWorkspace
                    ? "Manage all workspaces you own."
                    : "Multiple workspaces require a custom plan arranged with sales."}
                </p>

                {canMultiWorkspace ? (
                  <>
                    <div className="flex items-center justify-end gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0">
                      <button
                        type="button"
                        className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                        onClick={() => setShowCreateWorkspaceModal(true)}
                      >
                        Add Workspace
                      </button>
                    </div>
                    {allWorkspaces
                      .filter((w) => w.is_owner)
                      .map((ws) => {
                        const isActive = ws.id === workspace?.id;
                        return (
                          <div
                            className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0"
                            key={ws.id}
                          >
                            <div>
                              <div className="text-[13.5px] font-semibold">
                                {ws.name}
                                {isActive ? (
                                  <span className="ml-2 rounded-[6px] bg-[rgba(147,51,234,0.1)] px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--purple)">
                                    Active
                                  </span>
                                ) : null}
                              </div>
                              <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
                                {ws.project_count} {ws.project_count === 1 ? "project" : "projects"}{" "}
                                · {ws.member_count} {ws.member_count === 1 ? "member" : "members"}
                              </div>
                            </div>
                            <div className="flex flex-none gap-2.5">
                              {!isActive ? (
                                <button
                                  type="button"
                                  className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                                  onClick={() => {
                                    setActiveWorkspaceId(ws.id);
                                    window.location.reload();
                                  }}
                                >
                                  Switch
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                                disabled={
                                  isActive ||
                                  busyWorkspaceId === ws.id ||
                                  allWorkspaces.filter((w) => w.is_owner).length <= 1
                                }
                                onClick={() => void handleDeleteWorkspace(ws.id)}
                                title={
                                  isActive
                                    ? "Cannot delete the active workspace"
                                    : "Delete workspace"
                                }
                              >
                                {busyWorkspaceId === ws.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Trash2 className="h-4 w-4" />
                                )}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    {allWorkspaces.filter((w) => w.is_owner).length === 0 ? (
                      <p className="text-[12px] text-(--t-3)">No workspaces found.</p>
                    ) : null}
                  </>
                ) : (
                  // The approved design routes this to sales, not to an
                  // upgrade button: "Multiple workspaces require a custom plan
                  // arranged with sales", with Add Workspace disabled. Signal
                  // Gate.html says the same thing in as many words ("not
                  // included in any plan... the honest route is Contact
                  // sales, not an upgrade button"), and the approved Billing
                  // comparison matrix has no Multiple-workspaces row at all.
                  // Add Workspace is rendered disabled rather than removed
                  // because the design shows it disabled: it is the thing
                  // being described, and it cannot act.
                  <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
                    <div>
                      <div className="text-[13.5px] font-semibold">Multiple workspaces</div>
                      <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
                        Contact sales to enable creating and managing multiple isolated workspaces.
                      </div>
                    </div>
                    <div className="flex flex-none gap-2.5">
                      <button
                        type="button"
                        className="inline-flex h-[38px] items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) disabled:cursor-not-allowed disabled:opacity-55"
                        disabled
                      >
                        Add Workspace
                      </button>
                      <a
                        href={CONTACT_SALES_HREF}
                        className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                      >
                        Contact Sales
                      </a>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Team Panel ── */}
          {activeSection === "workspace-team" && (
            <div className="flex flex-col gap-[22px]">
              {/* Invite form card */}
              {canManage ? (
                <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
                  <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                    Invite Team Member
                  </h3>
                  <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
                    Members are scoped to this workspace only.
                  </p>
                  <div className="flex items-end gap-3 max-md:flex-col max-md:items-stretch">
                    <div className="mb-0 flex-1">
                      <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Email
                      </span>
                      <input
                        className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
                        type="text"
                        placeholder="teammate@company.com"
                        value={memberEmail}
                        onChange={(event) => setMemberEmail(event.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void handleAddMember();
                        }}
                      />
                    </div>
                    <div className="mb-0 max-w-[180px] flex-1">
                      <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Role
                      </span>
                      <select
                        className="field-focus-ring h-11 w-full appearance-none rounded-[14px] border-0 bg-[#EEF1F6] py-0 pl-[13px] pr-[34px] font-(family-name:--body-font) cursor-pointer text-[13.5px] text-(--t-1) outline-none wselect-chevron"
                        value={memberRole}
                        onChange={(event) =>
                          setMemberRole(event.target.value as InternalWorkspaceRole)
                        }
                      >
                        {INTERNAL_ROLE_OPTIONS.map((role) => (
                          <option key={role} value={role}>
                            {role.charAt(0) + role.slice(1).toLowerCase()}
                          </option>
                        ))}
                      </select>
                    </div>
                    <button
                      type="button"
                      className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                      onClick={handleAddMember}
                      disabled={isAddingMember}
                    >
                      {isAddingMember ? "Inviting…" : "Invite"}
                    </button>
                    {canMultiWorkspace && workspace?.is_owner ? (
                      <button
                        type="button"
                        className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                        onClick={() => setShowMultiInviteModal(true)}
                        title="Invite to multiple workspaces at once (owner only)"
                      >
                        <Users className="h-4 w-4" />
                        Multi-Workspace
                      </button>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {/* Team roster table */}
              <div className="rounded-[22px] border-0 bg-white">
                <div className="px-6 pt-[22px] pb-0">
                  <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                    Team Roster{" "}
                    <span className="font-normal text-(--t-3)">({internalMembers.length})</span>
                  </h3>
                </div>
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Team member
                      </th>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Role
                      </th>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-right font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="[&>tr:last-child>td]:border-b-0">
                    {internalMembers.map((member) => (
                      <tr key={member.user_id}>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          <div className="flex items-center gap-[11px]">
                            <span className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-[7px] bg-[#0c0f16] font-(family-name:--disp) text-[12px] font-bold text-white">
                              {member.email.slice(0, 2).toUpperCase()}
                            </span>
                            <div>
                              <div className="font-semibold">{member.email}</div>
                              <div className="font-(family-name:--mono) text-[11.5px] text-(--t-3)">
                                {member.is_owner ? "Owner" : "Member"}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          {member.is_owner ? (
                            <span className="rounded-[6px] bg-[rgba(147,51,234,0.1)] px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--purple)">
                              {member.role} · Owner
                            </span>
                          ) : (
                            <select
                              aria-label={`Role for ${member.email}`}
                              className="field-focus-ring h-11 w-full max-w-[160px] appearance-none rounded-[14px] border-0 bg-[#EEF1F6] py-0 pl-[13px] pr-[34px] font-(family-name:--body-font) cursor-pointer text-[13.5px] text-(--t-1) outline-none wselect-chevron"
                              value={member.role}
                              onChange={(event) =>
                                handleRoleUpdate(
                                  member.user_id,
                                  event.target.value as InternalWorkspaceRole
                                )
                              }
                              disabled={!canManage || busyUserId === member.user_id}
                            >
                              {INTERNAL_ROLE_OPTIONS.map((role) => (
                                <option key={role} value={role}>
                                  {role}
                                </option>
                              ))}
                            </select>
                          )}
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] text-right align-middle text-[13px]">
                          {member.is_owner ? (
                            <span className="text-(--t-3)">-</span>
                          ) : (
                            <button
                              type="button"
                              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                              onClick={() => handleRemoveMember(member.user_id)}
                              disabled={!canManage || busyUserId === member.user_id}
                              title="Remove workspace access"
                            >
                              {busyUserId === member.user_id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Trash2 className="h-4 w-4" />
                              )}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {internalMembers.length === 0 ? (
                      <tr>
                        <td
                          colSpan={3}
                          className="px-4 py-[13px] text-center align-middle text-[13px] text-(--t-3)"
                        >
                          No internal team members found.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Client Access Panel ── */}
          {activeSection === "workspace-client-access" && (
            <div className="flex flex-col gap-[22px]">
              {/* Invite form + project picker */}
              {canManage ? (
                <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
                  <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                    Invite Client
                  </h3>
                  <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
                    Invite stakeholders into the read-only portal with project-level access.
                  </p>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="mb-4 last:mb-0">
                      <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Client email
                      </span>
                      <input
                        className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
                        type="text"
                        placeholder="client@brand.com"
                        value={clientEmail}
                        onChange={(event) => setClientEmail(event.target.value)}
                      />
                    </div>
                    <div className="mb-4 last:mb-0">
                      <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Client name (optional)
                      </span>
                      <input
                        className="field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)"
                        type="text"
                        placeholder="Jane Client"
                        value={clientName}
                        onChange={(event) => setClientName(event.target.value)}
                      />
                    </div>
                  </div>

                  {/* Project picker */}
                  <div className="mb-4 last:mb-0">
                    <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      Project assignments{" "}
                      <span className="text-(--t-3)">
                        · {selectedClientProjectIds.length} selected
                      </span>
                    </span>
                    {projects.length > 0 ? (
                      <div className="flex flex-col gap-2">
                        {projects.map((project) => {
                          const checked = selectedClientProjectIds.includes(project.id);
                          return (
                            <label
                              key={project.id}
                              className="flex cursor-pointer items-center gap-[11px] rounded-[14px] border-0 bg-[#EEF1F6] px-3.5 py-3"
                            >
                              <input
                                type="checkbox"
                                className="h-4 w-4 accent-(--purple)"
                                checked={checked}
                                onChange={() => toggleClientProject(project.id)}
                              />
                              <span className="flex-1">
                                <b className="text-[13.5px]">{project.name}</b>
                                <br />
                                <small className="font-(family-name:--mono) text-[11.5px] text-(--t-3)">
                                  {stripDomainProtocol(project.domain_url)}
                                </small>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-[12px] text-(--t-3)">
                        Create a project before inviting portal users.
                      </p>
                    )}
                  </div>

                  <button
                    type="button"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                    onClick={handleInviteClient}
                    disabled={
                      projects.length === 0 ||
                      selectedClientProjectIds.length === 0 ||
                      isInvitingClient
                    }
                  >
                    {isInvitingClient ? "Inviting…" : "Invite Client"}
                  </button>

                  {manualInvitationUrl ? (
                    <div className="mt-[18px] mb-4 last:mb-0">
                      <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        Manual onboarding link
                      </span>
                      <p className="mb-2 text-[12px] text-(--t-3)">
                        Email delivery is disabled in this environment. Share this link directly.
                      </p>
                      <div className="break-all select-all rounded-[14px] border-0 bg-[#EEF1F6] px-3.5 py-3 font-(family-name:--mono) text-[12px]">
                        {manualInvitationUrl}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {/* Client roster table */}
              <div className="rounded-[22px] border-0 bg-white">
                <div className="px-6 pt-[22px] pb-0">
                  <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                    Portal Users{" "}
                    <span className="font-normal text-(--t-3)">({clientMembers.length})</span>
                  </h3>
                </div>
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Client user
                      </th>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Access
                      </th>
                      <th className="border-b border-b-(--line) px-4 py-[11px] text-right font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="[&>tr:last-child>td]:border-b-0">
                    {clientMembers.map((member) => (
                      <tr key={member.user_id}>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          <div className="flex items-center gap-[11px]">
                            <span className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-[7px] bg-[#0c0f16] font-(family-name:--disp) text-[12px] font-bold text-white">
                              {member.email.slice(0, 2).toUpperCase()}
                            </span>
                            <div>
                              <div className="font-semibold">{member.email}</div>
                              <div className="font-(family-name:--mono) text-[11.5px] text-(--t-3)">
                                Added {formatCreatedAt(member.created_at)}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                          <span className="rounded-[6px] bg-[rgba(147,51,234,0.1)] px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--purple)">
                            {member.role}
                          </span>
                        </td>
                        <td className="border-b border-b-(--line-2) px-4 py-[13px] text-right align-middle text-[13px]">
                          <button
                            type="button"
                            className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
                            onClick={() => handleRemoveMember(member.user_id)}
                            disabled={!canManage || busyUserId === member.user_id}
                            title="Remove portal access"
                          >
                            {busyUserId === member.user_id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Trash2 className="h-4 w-4" />
                            )}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {clientMembers.length === 0 ? (
                      <tr>
                        <td
                          colSpan={3}
                          className="px-4 py-[13px] text-center align-middle text-[13px] text-(--t-3)"
                        >
                          No client portal users invited yet.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── White-Label Panel ── */}
          {activeSection === "workspace-white-label" && (
            <WorkspaceWhiteLabelSection
              entitled={canWhiteLabel}
              canManage={workspace?.role === "ADMIN"}
              getAuthHeaders={getAuthHeaders}
            />
          )}

          {/* ── Developer Panel ── */}
          {activeSection === "workspace-developer" && (
            <div className="flex flex-col gap-[22px]">
              <WorkspaceCostBreakdownSection
                breakdown={costBreakdown}
                projects={projects}
                isLoading={isLoadingCostBreakdown}
                error={costBreakdownError}
                onRetry={() => {
                  void (async () => {
                    if (!workspace) {
                      return;
                    }
                    try {
                      const headers = await getAuthHeaders();
                      await loadCostBreakdown(workspace.id, headers);
                    } catch (err) {
                      setCostBreakdownError(
                        resolveErrorMessage(err, "Failed to load workspace cost breakdown.")
                      );
                    }
                  })();
                }}
              />

              <ApiKeysSection getAuthHeaders={getAuthHeaders} />
            </div>
          )}
        </SignalTabPanel>

        <CreateWorkspaceModal
          open={showCreateWorkspaceModal}
          onClose={() => setShowCreateWorkspaceModal(false)}
          getAuthHeaders={getAuthHeaders}
        />
        <InviteToMultipleWorkspacesModal
          open={showMultiInviteModal}
          onClose={() => setShowMultiInviteModal(false)}
          ownedWorkspaces={allWorkspaces.filter((w) => w.is_owner)}
          activeWorkspaceId={workspace?.id ?? null}
          getToken={getToken}
        />
      </div>
    </WorkspacePageFrame>
  );
}

export default WorkspaceSettingsPage;
