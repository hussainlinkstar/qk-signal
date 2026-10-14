"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Loader2, MessageSquareMore, Pencil, Reply, Shield, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/components/auth/custom-auth";
import AnnotationComposer from "@/components/dashboard/AnnotationComposer";
import Button from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";
import {
  createAuditAnnotation,
  deleteAuditAnnotation,
  fetchAuditAnnotations,
  updateAuditAnnotation,
  type AnnotationVisibility,
  type ReportAnnotation,
} from "@/services/annotationService";
import { fetchCurrentWorkspace } from "@/services/workspaceService";

type AuditAnnotationThreadProps = {
  auditId: string | number;
  sectionPath?: string | null;
  sourceRecommendationKey?: string | null;
  title: string;
  description?: string | null;
  onCountChange?: (count: number) => void;
};

const formatDateTime = (value: string | null | undefined) => {
  if (!value) {
    return "Just now";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Just now";
  }
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
};

const countAnnotations = (items: ReportAnnotation[]) =>
  items.reduce((sum, item) => sum + 1 + item.replies.length, 0);

const resolveDisplayName = (user: { name?: string; email?: string } | null | undefined) => {
  if (user?.name) {
    return user.name;
  }
  if (user?.email) {
    return user.email.split("@", 1)[0];
  }
  return "You";
};

export default function AuditAnnotationThread({
  auditId,
  sectionPath = null,
  sourceRecommendationKey = null,
  title,
  description = null,
  onCountChange,
}: AuditAnnotationThreadProps) {
  const { getToken, user, isSignedIn } = useAuth();
  const [items, setItems] = useState<ReportAnnotation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [replyParentId, setReplyParentId] = useState<number | null>(null);
  const [editingAnnotationId, setEditingAnnotationId] = useState<number | null>(null);
  const [canWrite, setCanWrite] = useState(false);
  const [accessResolved, setAccessResolved] = useState(false);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to manage report annotations.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadAccess = useCallback(async () => {
    if (!isSignedIn) {
      setCanWrite(false);
      setAccessResolved(true);
      return;
    }
    try {
      const headers = await getAuthHeaders();
      const workspace = await fetchCurrentWorkspace(headers);
      setCanWrite(
        ["ADMIN", "MANAGER", "EDITOR"].includes(String(workspace.role || "").toUpperCase())
      );
    } catch {
      setCanWrite(false);
    } finally {
      setAccessResolved(true);
    }
  }, [getAuthHeaders, isSignedIn]);

  const loadAnnotations = useCallback(async () => {
    if (!auditId) {
      setLoading(false);
      setItems([]);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const response = await fetchAuditAnnotations(auditId, headers, {
        sectionPath,
        sourceRecommendationKey,
        page: 1,
        perPage: 50,
      });
      setItems(response.items);
      onCountChange?.(countAnnotations(response.items));
    } catch (loadError) {
      const message =
        loadError instanceof Error ? loadError.message : "Failed to load annotations.";
      setError(message);
      onCountChange?.(0);
    } finally {
      setLoading(false);
    }
  }, [auditId, getAuthHeaders, onCountChange, sectionPath, sourceRecommendationKey]);

  useEffect(() => {
    void loadAccess();
  }, [loadAccess]);

  useEffect(() => {
    void loadAnnotations();
  }, [loadAnnotations]);

  const currentUserId = useMemo(() => Number(user?.id || 0) || null, [user?.id]);

  const handleCreate = async (payload: { content: string; visibility: AnnotationVisibility }) => {
    const previousItems = items;
    const temporaryId = -Date.now();
    const inheritedVisibility =
      (replyParentId
        ? previousItems.find((item) => item.id === replyParentId)?.visibility
        : payload.visibility) || payload.visibility;
    const optimisticAnnotation: ReportAnnotation = {
      id: temporaryId,
      audit_id: Number(auditId),
      project_id: 0,
      user_id: currentUserId,
      user_display_name: resolveDisplayName(user),
      parent_id: replyParentId,
      section_path: sectionPath,
      source_recommendation_key: sourceRecommendationKey,
      content: payload.content,
      visibility: inheritedVisibility,
      is_deleted: false,
      created_at: new Date().toISOString(),
      updated_at: null,
      can_edit: true,
      can_delete: true,
      replies: [],
    };
    const optimisticItems = replyParentId
      ? previousItems.map((item) =>
          item.id === replyParentId
            ? { ...item, replies: [...item.replies, optimisticAnnotation] }
            : item
        )
      : [...previousItems, optimisticAnnotation];

    setItems(optimisticItems);
    onCountChange?.(countAnnotations(optimisticItems));
    setBusyAction(replyParentId ? `reply:${replyParentId}` : "create");
    try {
      const headers = await getAuthHeaders();
      await createAuditAnnotation(
        auditId,
        {
          section_path: sectionPath,
          source_recommendation_key: sourceRecommendationKey,
          content: payload.content,
          visibility: payload.visibility,
          parent_id: replyParentId,
        },
        headers
      );
      setReplyParentId(null);
      toast.success(replyParentId ? "Reply added." : "Annotation added.");
      await loadAnnotations();
    } catch (actionError) {
      setItems(previousItems);
      onCountChange?.(countAnnotations(previousItems));
      toast.error(actionError instanceof Error ? actionError.message : "Save failed.");
    } finally {
      setBusyAction(null);
    }
  };

  const handleUpdate = async (
    annotation: ReportAnnotation,
    payload: { content: string; visibility: AnnotationVisibility }
  ) => {
    setBusyAction(`edit:${annotation.id}`);
    try {
      const headers = await getAuthHeaders();
      await updateAuditAnnotation(
        auditId,
        annotation.id,
        {
          content: payload.content,
          visibility: payload.visibility,
        },
        headers
      );
      setEditingAnnotationId(null);
      toast.success("Annotation updated.");
      await loadAnnotations();
    } catch (actionError) {
      toast.error(actionError instanceof Error ? actionError.message : "Update failed.");
    } finally {
      setBusyAction(null);
    }
  };

  const handleDelete = async (annotationId: number) => {
    setBusyAction(`delete:${annotationId}`);
    try {
      const headers = await getAuthHeaders();
      await deleteAuditAnnotation(auditId, annotationId, headers);
      toast.success("Annotation removed.");
      await loadAnnotations();
    } catch (actionError) {
      toast.error(actionError instanceof Error ? actionError.message : "Delete failed.");
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="rounded-4xl border border-(--line) bg-(--panel) p-6">
      <div className="flex flex-col gap-3 border-b border-(--line) pb-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.24em] text-primary">
              Report Thread
            </p>
            <h4 className="mt-2 text-xl font-black text-(--t-1)">{title}</h4>
          </div>
          <div className="rounded-full border border-(--line) bg-(--line-2) px-3 py-1 text-[10px] font-black uppercase tracking-[0.2em] text-(--t-2)">
            {countAnnotations(items)} items
          </div>
        </div>
        {description ? (
          <p className="max-w-3xl text-sm leading-7 text-(--t-2)">{description}</p>
        ) : null}
      </div>

      {loading ? (
        <div className="flex items-center gap-3 py-8 text-sm font-semibold text-(--t-2)">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading annotations...
        </div>
      ) : null}

      {!loading && error ? (
        <div className="py-8">
          <p className="text-sm font-semibold text-rose-300">{error}</p>
          <Button variant="ghost" size="sm" className="mt-3" onClick={() => void loadAnnotations()}>
            Retry
          </Button>
        </div>
      ) : null}

      {!loading && !error ? (
        <div className="space-y-5 pt-5">
          {items.length === 0 ? (
            <div className="rounded border border-dashed border-(--line) bg-(--line-2) p-6">
              <div className="flex items-start gap-3">
                <MessageSquareMore className="mt-0.5 h-5 w-5 text-(--t-3)" />
                <div>
                  <p className="text-sm font-semibold text-(--t-1)">No annotations yet</p>
                  <p className="mt-2 text-sm leading-7 text-(--t-2)">
                    {canWrite
                      ? "Add context for your team or mark this note as client-visible before sharing the report."
                      : "This section has no published annotation context yet."}
                  </p>
                </div>
              </div>
            </div>
          ) : (
            items.map((annotation) => {
              const isEditing = editingAnnotationId === annotation.id;
              return (
                <div
                  key={annotation.id}
                  className="rounded border border-(--line) bg-(--line-2) p-5"
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-(--t-1)">
                          {annotation.user_display_name || "Unknown author"}
                        </p>
                        <span
                          className={cx(
                            "rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.18em]",
                            annotation.visibility === "client_visible"
                              ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                              : "border-amber-400/20 bg-amber-500/10 text-amber-200"
                          )}
                        >
                          {annotation.visibility === "client_visible"
                            ? "Client visible"
                            : "Internal"}
                        </span>
                        {annotation.user_id === currentUserId ? (
                          <span className="rounded-full border border-(--line) px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.18em] text-(--t-3)">
                            You
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs uppercase tracking-[0.16em] text-(--t-3)">
                        {formatDateTime(annotation.updated_at || annotation.created_at)}
                      </p>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {annotation.can_edit ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            setEditingAnnotationId((current) =>
                              current === annotation.id ? null : annotation.id
                            )
                          }
                        >
                          <Pencil className="h-3.5 w-3.5" />
                          Edit
                        </Button>
                      ) : null}
                      {canWrite ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            setReplyParentId((current) =>
                              current === annotation.id ? null : annotation.id
                            )
                          }
                        >
                          <Reply className="h-3.5 w-3.5" />
                          Reply
                        </Button>
                      ) : null}
                      {annotation.can_delete ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void handleDelete(annotation.id)}
                          loading={busyAction === `delete:${annotation.id}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Delete
                        </Button>
                      ) : null}
                    </div>
                  </div>

                  {isEditing ? (
                    <div className="mt-4">
                      <AnnotationComposer
                        initialContent={annotation.content}
                        initialVisibility={
                          annotation.visibility === "client_visible" ? "client_visible" : "internal"
                        }
                        submitLabel="Save changes"
                        loading={busyAction === `edit:${annotation.id}`}
                        showVisibilityToggle={annotation.parent_id === null}
                        onCancel={() => setEditingAnnotationId(null)}
                        onSubmit={(payload) => handleUpdate(annotation, payload)}
                      />
                    </div>
                  ) : (
                    <div className="prose prose-invert mt-4 max-w-none text-sm prose-p:leading-7 prose-p:text-[var(--t-2)] prose-strong:text-[var(--t-1)]">
                      <ReactMarkdown skipHtml>{annotation.content}</ReactMarkdown>
                    </div>
                  )}

                  {annotation.replies.length > 0 ? (
                    <div className="mt-5 space-y-3 border-t border-(--line) pt-5">
                      {annotation.replies.map((reply) => (
                        <div
                          key={reply.id}
                          className="rounded border border-(--line) bg-(--paper) px-4 py-3"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-semibold text-(--t-1)">
                              {reply.user_display_name || "Unknown author"}
                            </p>
                            <span className="text-xs uppercase tracking-[0.16em] text-(--t-3)">
                              {formatDateTime(reply.updated_at || reply.created_at)}
                            </span>
                          </div>
                          <div className="prose prose-invert mt-3 max-w-none text-sm prose-p:leading-7 prose-p:text-[var(--t-2)] prose-strong:text-[var(--t-1)]">
                            <ReactMarkdown skipHtml>{reply.content}</ReactMarkdown>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {replyParentId === annotation.id ? (
                    <div className="mt-4 border-t border-(--line) pt-4">
                      <AnnotationComposer
                        submitLabel="Reply"
                        placeholder="Reply to this thread..."
                        loading={busyAction === `reply:${annotation.id}`}
                        initialVisibility={
                          annotation.visibility === "client_visible" ? "client_visible" : "internal"
                        }
                        showVisibilityToggle={false}
                        onCancel={() => setReplyParentId(null)}
                        onSubmit={(payload) => handleCreate(payload)}
                      />
                    </div>
                  ) : null}
                </div>
              );
            })
          )}

          {!accessResolved ? null : canWrite ? (
            <AnnotationComposer
              submitLabel="Add annotation"
              loading={busyAction === "create"}
              initialVisibility="internal"
              onSubmit={(payload) => handleCreate(payload)}
            />
          ) : (
            <div className="flex items-center gap-3 rounded border border-(--line) bg-(--line-2) px-4 py-3 text-sm text-(--t-2)">
              <Shield className="h-4 w-4 text-(--t-3)" />
              Viewer access can review threads but cannot add or edit annotations.
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
