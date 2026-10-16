"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, LogOut } from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import { cx } from "@/components/ui/utils";
import {
  fetchUserWorkspaces,
  fetchWorkspaceProjects,
  type WorkspaceProjectSummary,
  type WorkspaceSummary,
} from "@/services/workspaceService";
import {
  getActiveWorkspaceId,
  setActiveWorkspaceId,
  workspaceHeaders,
} from "@/components/app/WorkspaceSwitcher";

type Props = {
  email: string;
  onLogout: () => void;
  /**
   * Renders the approved project-scope `.ssw` (current project, menu listing
   * Projects) instead of the workspace-scope one.
   */
  projectScope?: boolean;
  /**
   * The project the switcher shows as current. Omitting it keeps the id in the
   * pathname, which is right inside `/dashboard/projects/<id>`; routes that
   * show a project from outside that segment (a scan, its history, a report)
   * pass the project they belong to so the control names it (SIGV2-1180).
   */
  activeProjectId?: string | null;
  /**
   * Status pages (/maintenance, the app 404) render while the API may be
   * down or the visitor anonymous: pass false so the switcher shows its
   * approved empty state without issuing any request.
   */
  fetchEnabled?: boolean;
  /**
   * Workspace-scope override for the trigger label. Admin passes its role
   * badge text; omitting it keeps the workspace-name/user-name fallback.
   */
  label?: string;
  /**
   * Overrides the mono kind label above the trigger ("WORKSPACE"/"PROJECT").
   * Omitting it keeps the scope-derived default.
   */
  kindLabel?: string;
  /**
   * Optional footnote rendered inside the open menu, below the identity
   * block. Admin uses it for the audited-access notice.
   */
  note?: React.ReactNode;
};

/* Flat welcome trigger — menu opens downward with a clear bordered panel. */
const MENU =
  "absolute inset-x-0 top-[calc(100%+8px)] z-30 rounded-2xl border border-(--line) bg-white p-2 shadow-[0_16px_40px_-16px_rgba(88,28,135,0.22)]";
const ITEM =
  "flex w-full items-center gap-[9px] rounded-xl px-3 py-2.5 text-start text-[13px] font-medium text-(--t-1) transition-colors hover:bg-(--purple-s)";
const DIVIDER = "mx-1 my-1.5 h-px bg-(--line)";
const SIGNOUT =
  "flex w-full items-center gap-[9px] rounded-xl px-3 py-2.5 text-start text-[13px] font-medium text-(--bad) transition-colors hover:bg-(--bad-s)";

const initialsFrom = (value: string) => {
  const parts = value.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
};

const stripScheme = (value?: string | null) =>
  value?.replace(/^https?:\/\//i, "").replace(/\/+$/, "") || null;

export default function SidebarWorkspaceMenu({
  email,
  onLogout,
  projectScope = false,
  activeProjectId: activeProjectIdProp = null,
  fetchEnabled = true,
  label,
  kindLabel: kindLabelOverride,
  note,
}: Props) {
  const { t } = useTranslation();
  const { getToken, isSignedIn, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [projects, setProjects] = useState<WorkspaceProjectSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) throw new Error("Sign in required");
    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  useEffect(() => {
    setActiveId(getActiveWorkspaceId());
  }, []);

  useEffect(() => {
    if (!isSignedIn || !fetchEnabled) {
      setWorkspaces([]);
      return;
    }
    const load = async () => {
      try {
        const headers = await getAuthHeaders();
        const list = await fetchUserWorkspaces(headers);
        setWorkspaces(list);
        const stored = getActiveWorkspaceId();
        const valid = list.find((w) => w.id === stored);
        if (!valid && list.length > 0) {
          setActiveWorkspaceId(list[0].id);
          setActiveId(list[0].id);
        } else if (valid) {
          setActiveId(valid.id);
        }
      } catch {
        setWorkspaces([]);
      }
    };
    void load();
  }, [getAuthHeaders, isSignedIn, fetchEnabled]);

  useEffect(() => {
    if (!isSignedIn || !projectScope || !fetchEnabled) {
      setProjects([]);
      return;
    }
    const load = async () => {
      try {
        setProjects(await fetchWorkspaceProjects(await getAuthHeaders()));
      } catch {
        setProjects([]);
      }
    };
    void load();
  }, [getAuthHeaders, isSignedIn, projectScope, fetchEnabled]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onEscape, true);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onEscape, true);
    };
  }, [open]);

  /* signal-MVP wireSideSwitch: ArrowUp/ArrowDown cycle focus through the
     menu's items; Escape (handled above) closes and restores the trigger. */
  const onMenuKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? []
    );
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "ArrowDown"
        ? (items[index + 1] ?? items[0])
        : (items[index - 1] ?? items[items.length - 1]);
    next.focus();
  };

  const activeProjectId = useMemo(
    () => activeProjectIdProp ?? pathname.match(/^\/dashboard\/projects\/([^/]+)/)?.[1] ?? "",
    [activeProjectIdProp, pathname]
  );
  // A deleted or inaccessible project can never stay selected: selection is
  // always resolved against the freshly fetched authorised list.
  const activeProject = projects.find((project) => String(project.id) === activeProjectId) ?? null;

  const activeWorkspace = workspaces.find((w) => w.id === activeId) ?? workspaces[0] ?? null;
  const workspaceName = activeWorkspace?.name ?? user?.name ?? t("signalShell.workspace");

  const kindLabel =
    kindLabelOverride ?? (projectScope ? t("signalShell.project") : t("signalShell.workspace"));
  const menuLabel = projectScope
    ? t("signalShell.projectMenuLabel")
    : t("signalShell.workspaceMenuLabel");
  const toggleLabel = projectScope
    ? (stripScheme(activeProject?.domain_url) ?? activeProject?.name ?? t("signalShell.project"))
    : (label ?? workspaceName);
  const displayName = user?.name?.trim() || email;
  const avatarLabel = displayName || toggleLabel || "?";
  const avatarInitials = initialsFrom(avatarLabel);

  const onSelectWorkspace = (workspace: WorkspaceSummary) => {
    setOpen(false);
    if (workspace.id === activeId) return;
    setActiveId(workspace.id);
    setActiveWorkspaceId(workspace.id);
    if (pathname !== "/dashboard") router.push("/dashboard");
    // Every cached query was fetched under the previous workspace's scope, so
    // switching back to an earlier workspace must refetch instead of replaying
    // the other workspace's projects and audits.
    router.refresh();
    void queryClient.invalidateQueries();
  };

  const onSelectProject = (project: WorkspaceProjectSummary) => {
    setOpen(false);
    const target = `/dashboard/projects/${project.id}`;
    if (target !== pathname) router.push(target);
    // Switching project must not leave a stale view: refresh server data and
    // drop every cached project-scoped query.
    router.refresh();
    void queryClient.invalidateQueries();
  };

  return (
    <div ref={containerRef} className="relative">
      <p className="sr-only">{kindLabel}</p>
      {open ? (
        <div
          ref={menuRef}
          role="menu"
          aria-label={menuLabel}
          className={MENU}
          onKeyDown={onMenuKeyDown}
        >
          {projectScope ? (
            <>
              {projects.map((project) => {
                const selected = String(project.id) === activeProjectId;
                return (
                  <button
                    key={project.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={selected}
                    onClick={() => onSelectProject(project)}
                    className={cx(
                      ITEM,
                      selected && "bg-(--purple-s) font-semibold text-(--purple-deep,var(--purple))"
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate text-start">
                      <span className="block truncate">{project.name}</span>
                      {project.domain_url ? (
                        <span
                          dir="ltr"
                          className="mt-0.5 block truncate text-[12px] font-medium text-(--t-2)"
                        >
                          {stripScheme(project.domain_url)}
                        </span>
                      ) : null}
                    </span>
                    {selected ? (
                      <Check size={14} className="ms-auto flex-none text-(--purple)" />
                    ) : null}
                  </button>
                );
              })}
            </>
          ) : (
            <>
              {workspaces.map((workspace) => {
                const selected = workspace.id === activeId;
                return (
                  <button
                    key={workspace.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={selected}
                    onClick={() => onSelectWorkspace(workspace)}
                    className={cx(
                      ITEM,
                      selected && "bg-(--purple-s) font-semibold text-(--purple-deep,var(--purple))"
                    )}
                  >
                    <span className="min-w-0 truncate text-start">{workspace.name}</span>
                    {selected ? (
                      <Check size={14} className="ms-auto flex-none text-(--purple)" />
                    ) : null}
                  </button>
                );
              })}
            </>
          )}
          <div className={DIVIDER} />
          {/* Approved `.ssw-who`: signed-in identity above Sign out. */}
          <div className="px-2.5 pb-1.5 pt-2">
            <span className="block truncate font-(family-name:--disp) text-[13px] font-bold text-(--t-1)">
              {displayName}
            </span>
            <span dir="ltr" className="block truncate text-start text-[12px] font-medium text-(--t-2)">
              {email}
            </span>
          </div>
          {note ? (
            <p className="mx-2.5 mb-1.5 text-[11.5px] leading-[1.45] text-(--t-3)">{note}</p>
          ) : null}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className={SIGNOUT}
          >
            <LogOut size={16} className="flex-none text-(--bad)" />
            {t("nav.signOut")}
          </button>
        </div>
      ) : null}

      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={menuLabel}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full cursor-pointer items-start gap-0 border-0 bg-transparent p-0 text-start transition-opacity hover:opacity-80"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[12px] font-medium text-(--t-2)">Welcome,</span>
          <span className="mt-0.5 flex items-center gap-1.5">
            <span
              dir="ltr"
              className="truncate font-(family-name:--disp) text-[18px] font-bold leading-tight tracking-[-0.02em] text-(--t-1)"
            >
              {displayName || toggleLabel}
            </span>
            <ChevronDown
              size={16}
              className={cx(
                "shrink-0 text-(--purple) transition-transform duration-200",
                open && "rotate-180"
              )}
            />
          </span>
          <span className="mt-1 block truncate text-[12px] font-medium text-(--t-2)">{toggleLabel}</span>
        </span>
        <span
          aria-hidden="true"
          className="ms-2 flex h-9 w-9 flex-none items-center justify-center rounded-[10px] bg-(--purple-s) text-[12px] font-bold text-(--purple)"
        >
          {avatarInitials}
        </span>
      </button>
    </div>
  );
}
