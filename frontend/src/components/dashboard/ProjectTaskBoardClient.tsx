"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Link2,
  Loader2,
  MoveDown,
  MoveUp,
  Plus,
  Rocket,
  RotateCcw,
  Trash2,
  UserRound,
} from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import Button from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";
import Modal from "@/components/ui/Modal";
import SelectField from "@/components/ui/SelectField";
import TextField from "@/components/ui/TextField";
import { cx } from "@/components/ui/utils";
import { formatDate, formatDateTime, formatRelativeTime } from "@/lib/dateFormat";
import {
  createProjectTask,
  deleteProjectTask,
  fetchProjectCmsConnections,
  fetchProjectCmsDeploymentLog,
  fetchProjectTaskImpact,
  fetchProjectTasks,
  previewTaskCmsChange,
  reorderProjectTasks,
  rollbackTaskCmsChange,
  pushTaskCmsChange,
  type CmsField,
  type ProjectCmsConnection,
  type ProjectCmsDeploymentLog,
  updateProjectTask,
  type ProjectTaskBoard,
  type ProjectTaskCreatePayload,
  type ProjectTaskImpact,
  type ProjectTaskItem,
  type ProjectTaskPriority,
  type ProjectTaskStatus,
  type TaskCmsPreview,
} from "@/services/workspaceService";

type Props = { projectId: string };

type TaskDraft = {
  title: string;
  description: string;
  status: ProjectTaskStatus;
  priority: ProjectTaskPriority;
  category: string;
  assigned_to_user_id: string;
  due_date: string;
};

type CmsDraft = {
  connectionId: string;
  pageUrl: string;
  field: CmsField;
  newValue: string;
};

const STATUS_ORDER: ProjectTaskStatus[] = ["todo", "in_progress", "done"];

const STATUS_META: Record<ProjectTaskStatus, { title: string; className: string }> = {
  todo: {
    title: "To Do",
    className:
      "border-[color-mix(in_srgb,var(--purple)_20%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] text-(--purple)",
  },
  in_progress: {
    title: "In Progress",
    className: "border-amber-400/20 bg-amber-400/10 text-amber-200",
  },
  done: { title: "Done", className: "border-emerald-400/20 bg-emerald-500/10 text-emerald-200" },
};

const PRIORITY_META: Record<ProjectTaskPriority, string> = {
  low: "border-(--line) bg-(--line-2) text-(--t-2)",
  medium: "border-sky-400/20 bg-sky-400/10 text-sky-200",
  high: "border-amber-400/20 bg-amber-400/10 text-amber-200",
  critical: "border-rose-400/20 bg-rose-500/10 text-rose-200",
};

const CMS_FIELD_OPTIONS: Array<{ value: CmsField; label: string }> = [
  { value: "head_scripts", label: "Head Scripts / JSON-LD" },
  { value: "meta_title", label: "Meta Title" },
  { value: "meta_description", label: "Meta Description" },
  { value: "alt_text", label: "Image Alt Text" },
];

/* ── Sanitise diff HTML from the CMS preview endpoint ──────────────── */
const DIFF_ALLOWED_TAGS = new Set([
  "span",
  "div",
  "p",
  "br",
  "ins",
  "del",
  "em",
  "strong",
  "b",
  "i",
  "code",
  "pre",
  "table",
  "thead",
  "tbody",
  "tr",
  "td",
  "th",
]);
const DIFF_ALLOWED_ATTRS = new Set(["class"]);

function sanitizeDiffHtml(raw: string): string {
  if (typeof window === "undefined") return "";
  const doc = new DOMParser().parseFromString(raw, "text/html");

  function walk(node: Node): Node | null {
    if (node.nodeType === Node.TEXT_NODE) return node.cloneNode(true);
    if (node.nodeType !== Node.ELEMENT_NODE) return null;

    const el = node as Element;
    const tag = el.tagName.toLowerCase();

    /* For disallowed tags keep the children, drop the wrapper */
    if (!DIFF_ALLOWED_TAGS.has(tag)) {
      const frag = document.createDocumentFragment();
      for (const child of Array.from(el.childNodes)) {
        const cleaned = walk(child);
        if (cleaned) frag.appendChild(cleaned);
      }
      return frag;
    }

    const clone = document.createElement(tag);
    for (const attr of Array.from(el.attributes)) {
      if (DIFF_ALLOWED_ATTRS.has(attr.name)) {
        clone.setAttribute(attr.name, attr.value);
      }
    }
    for (const child of Array.from(el.childNodes)) {
      const cleaned = walk(child);
      if (cleaned) clone.appendChild(cleaned);
    }
    return clone;
  }

  const frag = document.createDocumentFragment();
  for (const child of Array.from(doc.body.childNodes)) {
    const cleaned = walk(child);
    if (cleaned) frag.appendChild(cleaned);
  }
  const wrapper = document.createElement("div");
  wrapper.appendChild(frag);
  return wrapper.innerHTML;
}

const emptyDraft = (): TaskDraft => ({
  title: "",
  description: "",
  status: "todo",
  priority: "medium",
  category: "Technical",
  assigned_to_user_id: "",
  due_date: "",
});

const emptyCmsDraft = (): CmsDraft => ({
  connectionId: "",
  pageUrl: "",
  field: "head_scripts",
  newValue: "",
});

const sortTasks = (tasks: ProjectTaskItem[]) =>
  [...tasks].sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);

const buildColumns = (tasks: ProjectTaskItem[]) => ({
  todo: sortTasks(tasks.filter((task) => task.status === "todo")),
  in_progress: sortTasks(tasks.filter((task) => task.status === "in_progress")),
  done: sortTasks(tasks.filter((task) => task.status === "done")),
});

const draftFromTask = (task: ProjectTaskItem): TaskDraft => ({
  title: task.title,
  description: task.description || "",
  status: task.status,
  priority: task.priority,
  category: task.category,
  assigned_to_user_id: task.assigned_to_user_id ? String(task.assigned_to_user_id) : "",
  due_date: task.due_date || "",
});

export default function ProjectTaskBoardClient({ projectId }: Props) {
  const { getToken, isLoading: authLoading, isSignedIn } = useAuth();

  const [board, setBoard] = useState<ProjectTaskBoard | null>(null);
  const [impact, setImpact] = useState<ProjectTaskImpact | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [createDraft, setCreateDraft] = useState<TaskDraft>(emptyDraft);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [taskDraft, setTaskDraft] = useState<TaskDraft>(emptyDraft);
  const [cmsConnections, setCmsConnections] = useState<ProjectCmsConnection[]>([]);
  const [cmsLogs, setCmsLogs] = useState<ProjectCmsDeploymentLog[]>([]);
  const [cmsDraft, setCmsDraft] = useState<CmsDraft>(emptyCmsDraft);
  const [cmsPreview, setCmsPreview] = useState<TaskCmsPreview | null>(null);
  const [cmsBusy, setCmsBusy] = useState<"preview" | "push" | "rollback" | null>(null);
  const [cmsError, setCmsError] = useState<string | null>(null);
  const [cmsSuccess, setCmsSuccess] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) throw new Error("You must be signed in to manage project tasks.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadData = useCallback(async () => {
    if (!projectId || authLoading) return;
    if (!isSignedIn) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const [boardPayload, impactPayload, cmsConnectionPayload] = await Promise.all([
        fetchProjectTasks(projectId, headers),
        fetchProjectTaskImpact(projectId, headers),
        fetchProjectCmsConnections(projectId, headers).catch(() => []),
      ]);
      setBoard(boardPayload);
      setImpact(impactPayload);
      setCmsConnections(cmsConnectionPayload);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "Unable to load project task board."
      );
    } finally {
      setLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, projectId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const columns = useMemo(() => buildColumns(board?.tasks || []), [board?.tasks]);
  const selectedTask = useMemo(
    () => board?.tasks.find((task) => task.id === selectedTaskId) || null,
    [board?.tasks, selectedTaskId]
  );

  const loadCmsLogs = useCallback(
    async (taskId: number, connectionId?: number) => {
      try {
        const headers = await getAuthHeaders();
        const logs = await fetchProjectCmsDeploymentLog(projectId, headers, {
          taskId,
          connectionId,
          limit: 20,
        });
        setCmsLogs(logs);
      } catch {
        setCmsLogs([]);
      }
    },
    [getAuthHeaders, projectId]
  );

  useEffect(() => {
    if (!selectedTask) {
      setTaskDraft(emptyDraft());
      setCmsDraft(emptyCmsDraft());
      setCmsPreview(null);
      setCmsLogs([]);
      setCmsError(null);
      setCmsSuccess(null);
      return;
    }

    setTaskDraft(draftFromTask(selectedTask));
    setCmsPreview(null);
    setCmsError(null);
    setCmsSuccess(null);
    const preferredConnection =
      cmsConnections.find((connection) => connection.status === "verified") ||
      cmsConnections[0] ||
      null;
    setCmsDraft((current) => ({
      connectionId: preferredConnection
        ? String(preferredConnection.id)
        : current.connectionId || "",
      pageUrl: current.pageUrl,
      field: current.field,
      newValue: "",
    }));
    if (preferredConnection) {
      void loadCmsLogs(selectedTask.id, preferredConnection.id);
    } else {
      setCmsLogs([]);
    }
  }, [cmsConnections, loadCmsLogs, selectedTask]);

  useEffect(() => {
    if (!selectedTask) return;
    if (!cmsDraft.connectionId) {
      setCmsLogs([]);
      return;
    }
    void loadCmsLogs(selectedTask.id, Number(cmsDraft.connectionId));
  }, [cmsDraft.connectionId, loadCmsLogs, selectedTask]);

  const refreshAfterMutation = async () => {
    const headers = await getAuthHeaders();
    const [boardPayload, impactPayload, cmsConnectionPayload] = await Promise.all([
      fetchProjectTasks(projectId, headers),
      fetchProjectTaskImpact(projectId, headers),
      fetchProjectCmsConnections(projectId, headers).catch(() => []),
    ]);
    setBoard(boardPayload);
    setImpact(impactPayload);
    setCmsConnections(cmsConnectionPayload);
  };

  const saveCreate = async () => {
    if (!board?.can_edit) return;
    if (!createDraft.title.trim()) {
      setError("Add a task title before adding work to the board.");
      return;
    }

    setSaving(true);
    setError(null);
    setFeedback(null);
    try {
      const headers = await getAuthHeaders();
      const payload: ProjectTaskCreatePayload = {
        title: createDraft.title.trim(),
        description: createDraft.description.trim() || null,
        status: createDraft.status,
        priority: createDraft.priority,
        category: createDraft.category.trim() || "General",
        assigned_to_user_id: createDraft.assigned_to_user_id
          ? Number(createDraft.assigned_to_user_id)
          : null,
        due_date: createDraft.due_date || null,
      };
      await createProjectTask(projectId, payload, headers);
      setCreateDraft(emptyDraft());
      setFeedback("Task added to the board.");
      await refreshAfterMutation();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to create the task.");
    } finally {
      setSaving(false);
    }
  };

  const saveSelected = async () => {
    if (!selectedTask || !board?.can_edit) return;
    setSaving(true);
    setError(null);
    setFeedback(null);
    try {
      const headers = await getAuthHeaders();
      await updateProjectTask(
        projectId,
        selectedTask.id,
        {
          title: taskDraft.title.trim(),
          description: taskDraft.description.trim() || null,
          status: taskDraft.status,
          priority: taskDraft.priority,
          category: taskDraft.category.trim() || "General",
          assigned_to_user_id: taskDraft.assigned_to_user_id
            ? Number(taskDraft.assigned_to_user_id)
            : null,
          due_date: taskDraft.due_date || null,
        },
        headers
      );
      setFeedback("Task saved.");
      await refreshAfterMutation();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save the task.");
    } finally {
      setSaving(false);
    }
  };

  const removeSelected = async () => {
    if (!selectedTask || !board?.can_edit) return;
    setSaving(true);
    setError(null);
    setFeedback(null);
    try {
      const headers = await getAuthHeaders();
      await deleteProjectTask(projectId, selectedTask.id, headers);
      setSelectedTaskId(null);
      setFeedback("Task deleted.");
      await refreshAfterMutation();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete the task.");
    } finally {
      setSaving(false);
    }
  };

  const persistColumns = async (nextColumns: Record<ProjectTaskStatus, ProjectTaskItem[]>) => {
    if (!board?.can_edit) return;
    setSaving(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const nextBoard = await reorderProjectTasks(
        projectId,
        {
          columns: STATUS_ORDER.map((status) => ({
            status,
            task_ids: nextColumns[status].map((task) => task.id),
          })),
        },
        headers
      );
      const nextImpact = await fetchProjectTaskImpact(projectId, headers);
      setBoard(nextBoard);
      setImpact(nextImpact);
    } catch (persistError) {
      setError(
        persistError instanceof Error ? persistError.message : "Unable to reorder project tasks."
      );
    } finally {
      setSaving(false);
    }
  };

  const moveTask = async (task: ProjectTaskItem, nextStatus: ProjectTaskStatus) => {
    const nextColumns = buildColumns(board?.tasks || []);
    nextColumns[task.status] = nextColumns[task.status].filter((entry) => entry.id !== task.id);
    nextColumns[nextStatus] = [...nextColumns[nextStatus], { ...task, status: nextStatus }];
    await persistColumns(nextColumns);
  };

  const shiftTask = async (task: ProjectTaskItem, direction: -1 | 1) => {
    const nextColumns = buildColumns(board?.tasks || []);
    const column = [...nextColumns[task.status]];
    const currentIndex = column.findIndex((entry) => entry.id === task.id);
    const nextIndex = currentIndex + direction;
    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= column.length) return;
    [column[currentIndex], column[nextIndex]] = [column[nextIndex], column[currentIndex]];
    nextColumns[task.status] = column;
    await persistColumns(nextColumns);
  };

  const latestPushedCmsLog = useMemo(
    () => cmsLogs.find((entry) => entry.status === "pushed") || null,
    [cmsLogs]
  );

  const runCmsPreview = async () => {
    if (!selectedTask || !board?.can_edit) return;
    if (!cmsDraft.connectionId) {
      setCmsError("Select a CMS connection first.");
      return;
    }
    if (!cmsDraft.pageUrl.trim()) {
      setCmsError("Add the target page URL before previewing.");
      return;
    }

    setCmsBusy("preview");
    setCmsError(null);
    setCmsSuccess(null);
    try {
      const headers = await getAuthHeaders();
      const preview = await previewTaskCmsChange(
        selectedTask.id,
        {
          connection_id: Number(cmsDraft.connectionId),
          page_url: cmsDraft.pageUrl.trim(),
          field: cmsDraft.field,
          new_value: cmsDraft.newValue.trim() || undefined,
        },
        headers
      );
      setCmsPreview(preview);
      setCmsSuccess("Preview ready. Review the diff, then confirm the push.");
    } catch (previewError) {
      setCmsPreview(null);
      setCmsError(
        previewError instanceof Error ? previewError.message : "Unable to build CMS preview."
      );
    } finally {
      setCmsBusy(null);
    }
  };

  const runCmsPush = async () => {
    if (!selectedTask || !board?.can_edit) return;
    if (!cmsPreview) {
      setCmsError("Run a preview and use the generated confirmation token before pushing.");
      return;
    }

    setCmsBusy("push");
    setCmsError(null);
    setCmsSuccess(null);
    try {
      const headers = await getAuthHeaders();
      const payload = await pushTaskCmsChange(
        selectedTask.id,
        {
          connection_id: Number(cmsDraft.connectionId),
          page_url: cmsDraft.pageUrl.trim(),
          field: cmsDraft.field,
          confirmation_token: cmsPreview.confirmation_token,
          new_value: cmsDraft.newValue.trim() || undefined,
        },
        headers
      );
      if (!payload.success) {
        setCmsError(payload.error_message || "CMS push failed.");
      } else {
        setCmsSuccess("Fix pushed to CMS and deployment log captured.");
        setCmsPreview(null);
      }
      await refreshAfterMutation();
      await loadCmsLogs(selectedTask.id, Number(cmsDraft.connectionId));
    } catch (pushError) {
      setCmsError(pushError instanceof Error ? pushError.message : "Unable to push to CMS.");
    } finally {
      setCmsBusy(null);
    }
  };

  const runCmsRollback = async () => {
    if (!selectedTask || !board?.can_edit || !latestPushedCmsLog) return;
    setCmsBusy("rollback");
    setCmsError(null);
    setCmsSuccess(null);
    try {
      const headers = await getAuthHeaders();
      const payload = await rollbackTaskCmsChange(
        selectedTask.id,
        {
          connection_id: Number(cmsDraft.connectionId),
          deployment_log_id: latestPushedCmsLog.id,
        },
        headers
      );
      if (!payload.success) {
        setCmsError(payload.error_message || "CMS rollback failed.");
      } else {
        setCmsSuccess("Last CMS deployment rolled back successfully.");
      }
      await refreshAfterMutation();
      await loadCmsLogs(selectedTask.id, Number(cmsDraft.connectionId));
    } catch (rollbackError) {
      setCmsError(
        rollbackError instanceof Error
          ? rollbackError.message
          : "Unable to roll back CMS deployment."
      );
    } finally {
      setCmsBusy(null);
    }
  };

  if (authLoading || loading) {
    return (
      <GlassCard className="border-(--line) bg-(--background-deep) p-8">
        <div className="flex items-center gap-3 text-sm font-black uppercase tracking-[0.22em] text-(--purple)">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading project task board...
        </div>
      </GlassCard>
    );
  }

  if (!isSignedIn) {
    return (
      <GlassCard className="border-(--line) bg-(--background-deep) p-8">
        <p className="text-sm font-semibold text-(--t-2)">
          Sign in to review native project task management.
        </p>
      </GlassCard>
    );
  }

  if (!board) {
    return (
      <GlassCard className="border-(--line) bg-(--background-deep) p-8">
        <p className="text-sm font-semibold text-rose-300">
          {error || "The project task board is unavailable right now."}
        </p>
      </GlassCard>
    );
  }

  const noAuditHistory = !board.latest_audit_id && board.tasks.length === 0;

  return (
    <div className="space-y-8">
      <GlassCard className="border-(--line) bg-(--background-deep) p-8">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded border border-[color-mix(in_srgb,var(--purple)_25%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] text-(--purple)">
                <ClipboardList className="h-5 w-5" />
              </div>
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--purple)">
                  Native Task Board
                </p>
                <h3 className="mt-1 text-2xl font-black tracking-tight text-(--t-1)">
                  Convert recommendations into managed delivery work
                </h3>
              </div>
            </div>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-(--t-2)">
              Tasks auto-populate from audit recommendations, track execution by column, and
              validate completed fixes against the next project audit.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <div className="rounded border-0 bg-(--line-2) px-4 py-3 text-[10px] font-black uppercase tracking-[0.24em] text-(--t-2)">
              {board.tasks.length} tracked tasks
            </div>
            <div className="rounded border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-[10px] font-black uppercase tracking-[0.24em] text-emerald-200">
              {impact?.summary.validated_count ?? 0} validated fixes
            </div>
          </div>
        </div>

        {board.can_edit ? null : (
          <div className="mt-6 rounded border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm font-semibold text-amber-100">
            This board is read-only for your current workspace role.
          </div>
        )}
        {feedback ? (
          <p className="mt-6 text-sm font-semibold text-emerald-300">{feedback}</p>
        ) : null}
        {error ? <p className="mt-3 text-sm font-semibold text-rose-300">{error}</p> : null}
      </GlassCard>

      <div className="grid gap-6 xl:grid-cols-[1.05fr_2fr]">
        <GlassCard className="border-(--line) bg-(--background-deep) p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.22em] text-(--purple)">
                Manual Intake
              </p>
              <h4 className="mt-2 text-xl font-black text-(--t-1)">
                Add project work outside the audit feed
              </h4>
            </div>
            <div className="rounded border-0 bg-(--line-2) px-4 py-3 text-[10px] font-black uppercase tracking-[0.24em] text-(--t-2)">
              Latest audit{" "}
              {board.latest_audit_at ? formatRelativeTime(board.latest_audit_at) : "not available"}
            </div>
          </div>

          {noAuditHistory ? (
            <div className="mt-6 rounded-4xl border border-dashed border-(--line) bg-(--line-2) p-5">
              <p className="text-lg font-black text-(--t-1)">No assessment-backed tasks yet</p>
              <p className="mt-2 text-sm leading-7 text-(--t-2)">
                Run an audit first so recommendations land in the board automatically, or add manual
                work now and validate it later.
              </p>
              <Link
                href={`/dashboard/audit?projectId=${projectId}`}
                className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-(--purple) transition hover:text-(--t-1)"
              >
                Run project audit
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          ) : null}

          <div className="mt-6 space-y-4">
            <TextField
              id="task-title"
              label="Task Title"
              value={createDraft.title}
              onChange={(event) =>
                setCreateDraft((current) => ({ ...current, title: event.target.value }))
              }
              disabled={!board.can_edit || saving}
              className="bg-(--line-2) border-(--line)"
            />
            <div className="space-y-1.5">
              <label
                htmlFor="task-description"
                className="text-xs font-semibold uppercase tracking-[0.18em] text-(--t-3)"
              >
                Delivery Notes
              </label>
              <textarea
                id="task-description"
                rows={4}
                value={createDraft.description}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, description: event.target.value }))
                }
                disabled={!board.can_edit || saving}
                className="w-full rounded-xl border-0 bg-(--line-2) px-4 py-3 text-sm text-(--t-1) focus-visible:border-primary focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-primary"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <SelectField
                id="task-priority"
                label="Priority"
                value={createDraft.priority}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setCreateDraft((current) => ({
                    ...current,
                    priority: event.target.value as ProjectTaskPriority,
                  }))
                }
                className="bg-(--line-2) border-(--line)"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </SelectField>
              <SelectField
                id="task-status"
                label="Starting Column"
                value={createDraft.status}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setCreateDraft((current) => ({
                    ...current,
                    status: event.target.value as ProjectTaskStatus,
                  }))
                }
                className="bg-(--line-2) border-(--line)"
              >
                {STATUS_ORDER.map((status) => (
                  <option key={status} value={status}>
                    {STATUS_META[status].title}
                  </option>
                ))}
              </SelectField>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <TextField
                id="task-category"
                label="Category"
                value={createDraft.category}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, category: event.target.value }))
                }
                disabled={!board.can_edit || saving}
                className="bg-(--line-2) border-(--line)"
              />
              <SelectField
                id="task-assignee"
                label="Assignee"
                value={createDraft.assigned_to_user_id}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setCreateDraft((current) => ({
                    ...current,
                    assigned_to_user_id: event.target.value,
                  }))
                }
                className="bg-(--line-2) border-(--line)"
              >
                <option value="">Unassigned</option>
                {board.assignees.map((assignee) => (
                  <option key={assignee.user_id} value={String(assignee.user_id)}>
                    {assignee.email}
                  </option>
                ))}
              </SelectField>
              <TextField
                id="task-due-date"
                label="Due Date"
                type="date"
                value={createDraft.due_date}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, due_date: event.target.value }))
                }
                disabled={!board.can_edit || saving}
                className="bg-(--line-2) border-(--line)"
              />
            </div>
            <Button
              onClick={() => void saveCreate()}
              loading={saving}
              disabled={!board.can_edit}
              className="rounded px-5 py-3 text-[11px] font-black uppercase tracking-[0.22em]"
            >
              <Plus className="h-4 w-4" />
              Add Task
            </Button>
          </div>
        </GlassCard>

        <div className="grid gap-5 xl:grid-cols-3">
          {STATUS_ORDER.map((status) => (
            <div
              key={status}
              className="rounded-4xl border-0 bg-(--background-deep) p-5"
            >
              <div className="flex items-center justify-between gap-3">
                <span
                  className={cx(
                    "rounded-full border px-3 py-1 text-[10px] font-black uppercase tracking-[0.22em]",
                    STATUS_META[status].className
                  )}
                >
                  {STATUS_META[status].title}
                </span>
                <span className="rounded border-0 bg-(--line-2) px-3 py-2 text-sm font-black text-(--t-1)">
                  {columns[status].length}
                </span>
              </div>
              <div className="mt-5 space-y-3">
                {columns[status].length === 0 ? (
                  <div className="rounded-4xl border border-dashed border-(--line) bg-(--line-2) p-5 text-sm text-(--t-3)">
                    No tasks in this column yet.
                  </div>
                ) : null}
                {columns[status].map((task, index) => (
                  <div
                    key={task.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedTaskId(task.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedTaskId(task.id);
                      }
                    }}
                    className="w-full rounded-4xl border-0 bg-(--line-2) p-4 text-left transition hover:border-cyan-300/30 hover:bg-(--line-2)"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cx(
                          "rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em]",
                          PRIORITY_META[task.priority]
                        )}
                      >
                        {task.priority}
                      </span>
                      <span className="rounded-full border-0 bg-(--line-2) px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-(--t-2)">
                        {task.category}
                      </span>
                    </div>
                    <p className="mt-3 text-base font-black leading-tight text-(--t-1)">
                      {task.title}
                    </p>
                    {task.description ? (
                      <p className="mt-2 line-clamp-3 text-sm leading-6 text-(--t-2)">
                        {task.description}
                      </p>
                    ) : null}
                    <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-(--t-3)">
                      <span className="inline-flex items-center gap-1.5">
                        <UserRound className="h-3.5 w-3.5" />
                        {task.assignee?.email || "Unassigned"}
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <CalendarClock className="h-3.5 w-3.5" />
                        {task.due_date ? formatDate(task.due_date) : "No due date"}
                      </span>
                      {task.verified_at ? (
                        <span className="inline-flex items-center gap-1.5 text-emerald-300">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Validated {formatRelativeTime(task.verified_at)}
                        </span>
                      ) : null}
                    </div>
                    {board.can_edit ? (
                      <div
                        className="mt-4 flex flex-wrap items-center gap-2"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={index === 0 || saving}
                          onClick={() => void shiftTask(task, -1)}
                          className="rounded-xl border-0 bg-(--line-2) text-(--t-2) hover:bg-(--line-2)"
                        >
                          <MoveUp className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={index === columns[status].length - 1 || saving}
                          onClick={() => void shiftTask(task, 1)}
                          className="rounded-xl border-0 bg-(--line-2) text-(--t-2) hover:bg-(--line-2)"
                        >
                          <MoveDown className="h-4 w-4" />
                        </Button>
                        <SelectField
                          aria-label={`Move ${task.title} to another column`}
                          value={task.status}
                          disabled={saving}
                          onChange={(event) =>
                            void moveTask(task, event.target.value as ProjectTaskStatus)
                          }
                          className="max-w-[180px] bg-(--line-2)"
                        >
                          {STATUS_ORDER.map((option) => (
                            <option key={option} value={option}>
                              {STATUS_META[option].title}
                            </option>
                          ))}
                        </SelectField>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <GlassCard className="border-(--line) bg-(--background-deep) p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--purple)">
              Resolved Impact
            </p>
            <h4 className="mt-2 text-xl font-black text-(--t-1)">Audit-validated score movement</h4>
          </div>
          <div className="rounded border-0 bg-(--line-2) px-4 py-3 text-[10px] font-black uppercase tracking-[0.24em] text-(--t-2)">
            Strongest lift{" "}
            {impact?.summary.strongest_metric
              ? `${impact.summary.strongest_metric.toUpperCase()} +${impact.summary.strongest_delta}`
              : "pending"}
          </div>
        </div>
        <div className="mt-6 space-y-3">
          {!impact || impact.items.length === 0 ? (
            <div className="rounded-4xl border border-dashed border-(--line) bg-(--line-2) p-6 text-sm text-(--t-3)">
              Complete a task and wait for the next audit to see score attribution here.
            </div>
          ) : (
            impact.items.map((item) => (
              <div
                key={item.task_id}
                className="rounded-4xl border-0 bg-(--line-2) p-5"
              >
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="text-lg font-black text-(--t-1)">{item.title}</p>
                    <p className="mt-2 text-sm leading-7 text-(--t-2)">
                      {item.narrative ||
                        "The task is complete, but a later assessment has not confirmed the score effect yet."}
                    </p>
                  </div>
                  <div className="grid min-w-[240px] grid-cols-2 gap-3">
                    {(["seo", "geo", "aeo", "overall"] as const).map((metric) => (
                      <div
                        key={metric}
                        className="rounded border-0 bg-(--line-2) px-4 py-3"
                      >
                        <p className="text-[10px] font-black uppercase tracking-[0.22em] text-(--t-3)">
                          {metric}
                        </p>
                        <p className="mt-2 text-xl font-black text-(--t-1)">
                          {typeof item.delta[metric] === "number"
                            ? `${item.delta[metric]! > 0 ? "+" : ""}${item.delta[metric]}`
                            : "--"}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </GlassCard>

      <Modal
        open={Boolean(selectedTask)}
        onClose={() => setSelectedTaskId(null)}
        panelClassName="w-full max-w-3xl border-(--line) bg-(--background-deep)"
      >
        {selectedTask ? (
          <div className="space-y-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--purple)">
                  Task Detail
                </p>
                <h4 className="mt-2 text-2xl font-black text-(--t-1)">{selectedTask.title}</h4>
                <p className="mt-2 text-sm text-(--t-2)">
                  Created{" "}
                  {selectedTask.created_at ? formatDateTime(selectedTask.created_at) : "recently"}
                </p>
              </div>
              {selectedTask.origin === "audit_recommendation" ? (
                <div className="rounded border border-[color-mix(in_srgb,var(--purple)_20%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] px-4 py-3 text-[10px] font-black uppercase tracking-[0.22em] text-(--purple)">
                  Auto-created from audit
                </div>
              ) : null}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <TextField
                id="modal-task-title"
                label="Title"
                value={taskDraft.title}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setTaskDraft((current) => ({ ...current, title: event.target.value }))
                }
                className="bg-(--line-2) border-(--line)"
              />
              <TextField
                id="modal-task-category"
                label="Category"
                value={taskDraft.category}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setTaskDraft((current) => ({ ...current, category: event.target.value }))
                }
                className="bg-(--line-2) border-(--line)"
              />
            </div>
            <div className="space-y-1.5">
              <label
                htmlFor="modal-task-description"
                className="text-xs font-semibold uppercase tracking-[0.18em] text-(--t-3)"
              >
                Delivery Notes
              </label>
              <textarea
                id="modal-task-description"
                rows={5}
                value={taskDraft.description}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setTaskDraft((current) => ({ ...current, description: event.target.value }))
                }
                className="w-full rounded-xl border-0 bg-(--line-2) px-4 py-3 text-sm text-(--t-1) focus-visible:border-primary focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-primary"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <SelectField
                id="modal-task-status"
                label="Status"
                value={taskDraft.status}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setTaskDraft((current) => ({
                    ...current,
                    status: event.target.value as ProjectTaskStatus,
                  }))
                }
                className="bg-(--line-2) border-(--line)"
              >
                {STATUS_ORDER.map((status) => (
                  <option key={status} value={status}>
                    {STATUS_META[status].title}
                  </option>
                ))}
              </SelectField>
              <SelectField
                id="modal-task-priority"
                label="Priority"
                value={taskDraft.priority}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setTaskDraft((current) => ({
                    ...current,
                    priority: event.target.value as ProjectTaskPriority,
                  }))
                }
                className="bg-(--line-2) border-(--line)"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </SelectField>
              <SelectField
                id="modal-task-assignee"
                label="Assignee"
                value={taskDraft.assigned_to_user_id}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setTaskDraft((current) => ({
                    ...current,
                    assigned_to_user_id: event.target.value,
                  }))
                }
                className="bg-(--line-2) border-(--line)"
              >
                <option value="">Unassigned</option>
                {board.assignees.map((assignee) => (
                  <option key={assignee.user_id} value={String(assignee.user_id)}>
                    {assignee.email}
                  </option>
                ))}
              </SelectField>
              <TextField
                id="modal-task-due-date"
                label="Due Date"
                type="date"
                value={taskDraft.due_date}
                disabled={!board.can_edit || saving}
                onChange={(event) =>
                  setTaskDraft((current) => ({ ...current, due_date: event.target.value }))
                }
                className="bg-(--line-2) border-(--line)"
              />
            </div>

            <div className="rounded-4xl border-0 bg-(--line-2) p-4 text-sm text-(--t-2)">
              <div className="flex flex-wrap gap-6">
                <span>
                  Source assessment:{" "}
                  <span className="font-semibold text-(--t-1)">
                    {selectedTask.source_audit_id || "Manual task"}
                  </span>
                </span>
                <span>
                  Validated:{" "}
                  <span className="font-semibold text-(--t-1)">
                    {selectedTask.verified_at
                      ? formatDateTime(selectedTask.verified_at)
                      : "Pending"}
                  </span>
                </span>
                <span>
                  Resolution:{" "}
                  <span className="font-semibold text-(--t-1)">
                    {selectedTask.resolution_source || "Open"}
                  </span>
                </span>
              </div>
            </div>

            <div className="rounded-4xl border-0 bg-(--line-2) p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[10px] font-black uppercase tracking-[0.22em] text-(--purple)">
                    Push To CMS
                  </p>
                  <h5 className="mt-2 text-lg font-black text-(--t-1)">
                    Preview, confirm, and deploy this fix to production
                  </h5>
                </div>
                <div className="rounded border-0 bg-(--line-2) px-3 py-2 text-[10px] font-black uppercase tracking-[0.2em] text-(--t-2)">
                  {cmsConnections.length} connection{cmsConnections.length === 1 ? "" : "s"}
                </div>
              </div>

              {!board.can_edit ? (
                <p className="mt-4 text-sm font-semibold text-amber-100">
                  CMS push is read-only for your current role.
                </p>
              ) : cmsConnections.length === 0 ? (
                <div className="mt-5 rounded border border-dashed border-(--line) bg-(--line-2) p-4 text-sm text-(--t-2)">
                  <p>No CMS connection is configured for this project.</p>
                  <Link
                    href="/dashboard/connections"
                    className="mt-2 inline-flex items-center gap-2 font-semibold text-(--purple) hover:text-(--t-1)"
                  >
                    Connect WordPress or Shopify
                    <Link2 className="h-4 w-4" />
                  </Link>
                </div>
              ) : (
                <div className="mt-5 space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <SelectField
                      id="cms-connection"
                      label="CMS Connection"
                      value={cmsDraft.connectionId}
                      disabled={Boolean(cmsBusy)}
                      onChange={(event) =>
                        setCmsDraft((current) => ({
                          ...current,
                          connectionId: event.target.value,
                        }))
                      }
                      className="bg-(--line-2) border-(--line)"
                    >
                      <option value="">Select connection</option>
                      {cmsConnections.map((connection) => (
                        <option key={connection.id} value={String(connection.id)}>
                          {connection.cms_type.toUpperCase()} - {connection.site_url} (
                          {connection.status})
                        </option>
                      ))}
                    </SelectField>
                    <TextField
                      id="cms-page-url"
                      label="Target Page URL"
                      value={cmsDraft.pageUrl}
                      disabled={Boolean(cmsBusy)}
                      onChange={(event) =>
                        setCmsDraft((current) => ({
                          ...current,
                          pageUrl: event.target.value,
                        }))
                      }
                      className="bg-(--line-2) border-(--line)"
                      placeholder="https://example.com/target-page"
                    />
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <SelectField
                      id="cms-field"
                      label="Field To Update"
                      value={cmsDraft.field}
                      disabled={Boolean(cmsBusy)}
                      onChange={(event) =>
                        setCmsDraft((current) => ({
                          ...current,
                          field: event.target.value as CmsField,
                        }))
                      }
                      className="bg-(--line-2) border-(--line)"
                    >
                      {CMS_FIELD_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </SelectField>
                    <TextField
                      id="cms-new-value"
                      label="Override Value (Optional)"
                      value={cmsDraft.newValue}
                      disabled={Boolean(cmsBusy)}
                      onChange={(event) =>
                        setCmsDraft((current) => ({
                          ...current,
                          newValue: event.target.value,
                        }))
                      }
                      className="bg-(--line-2) border-(--line)"
                      placeholder="Leave empty to use task snippet/description"
                    />
                  </div>

                  <div className="flex flex-wrap gap-3">
                    <Button
                      variant="ghost"
                      onClick={() => void runCmsPreview()}
                      loading={cmsBusy === "preview"}
                      className="px-4 py-3"
                    >
                      <Loader2
                        className={cx("h-4 w-4", cmsBusy === "preview" ? "animate-spin" : "")}
                      />
                      Preview Change
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => void runCmsPush()}
                      loading={cmsBusy === "push"}
                      disabled={!cmsPreview}
                      className="px-4 py-3"
                    >
                      <Rocket className="h-4 w-4" />
                      Confirm & Push
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => void runCmsRollback()}
                      loading={cmsBusy === "rollback"}
                      disabled={!latestPushedCmsLog}
                      className="rounded border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-amber-100 hover:bg-amber-500/20"
                    >
                      <RotateCcw className="h-4 w-4" />
                      Rollback Last Push
                    </Button>
                  </div>

                  {cmsError ? (
                    <p className="rounded border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm font-semibold text-rose-200">
                      {cmsError}
                    </p>
                  ) : null}
                  {cmsSuccess ? (
                    <p className="rounded border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm font-semibold text-emerald-200">
                      {cmsSuccess}
                    </p>
                  ) : null}

                  {cmsPreview ? (
                    <div className="space-y-3 rounded border border-[color-mix(in_srgb,var(--purple)_20%,transparent)] bg-cyan-500/5 p-4">
                      <div className="flex items-center gap-2 text-sm font-semibold text-cyan-100">
                        <CheckCircle2 className="h-4 w-4" />
                        Preview ready. Token expires in {
                          cmsPreview.confirmation_expires_in_seconds
                        }{" "}
                        seconds.
                      </div>
                      <div
                        className="cms-diff-preview rounded border-0 bg-black/30 p-4 text-sm text-(--t-2)"
                        dangerouslySetInnerHTML={{ __html: sanitizeDiffHtml(cmsPreview.diff_html) }}
                      />
                    </div>
                  ) : (
                    <div className="rounded border border-dashed border-(--line) bg-(--line-2) p-4 text-sm text-(--t-2)">
                      Run Preview Change to generate the confirmation token and diff.
                    </div>
                  )}

                  {cmsLogs.length > 0 ? (
                    <div className="space-y-2 rounded border-0 bg-black/30 p-4">
                      <p className="text-[10px] font-black uppercase tracking-[0.2em] text-(--t-3)">
                        Recent Deployments
                      </p>
                      {cmsLogs.slice(0, 3).map((entry) => (
                        <div
                          key={entry.id}
                          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border-0 bg-(--line-2) px-3 py-2 text-xs text-(--t-2)"
                        >
                          <span className="inline-flex items-center gap-1.5">
                            {entry.status === "failed" ? (
                              <AlertTriangle className="h-3.5 w-3.5 text-rose-300" />
                            ) : (
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
                            )}
                            {entry.status}
                          </span>
                          <span>{entry.field_changed}</span>
                          <span>
                            {entry.created_at ? formatRelativeTime(entry.created_at) : "just now"}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-(--t-3)">
                {selectedTask.verified_at
                  ? `Validated ${formatRelativeTime(selectedTask.verified_at)}`
                  : "This task has not been validated by a later assessment yet."}
              </div>
              <div className="flex flex-wrap gap-3">
                {board.can_edit ? (
                  <Button
                    variant="danger"
                    onClick={() => void removeSelected()}
                    loading={saving}
                    className="px-4 py-3"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  onClick={() => setSelectedTaskId(null)}
                  className="px-4 py-3"
                >
                  Close
                </Button>
                {board.can_edit ? (
                  <Button
                    variant="outline"
                    onClick={() => void saveSelected()}
                    loading={saving}
                    className="px-4 py-3"
                  >
                    Save Task
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
