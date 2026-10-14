"use client";

import React, { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Loader2, MessageSquareMore, Reply } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/components/auth/custom-auth";
import AnnotationComposer from "@/components/dashboard/AnnotationComposer";
import Button from "@/components/ui/Button";
import {
  createPortalAnnotationReply,
  fetchPortalAuditAnnotations,
  type ReportAnnotation,
} from "@/services/annotationService";

type PortalAnnotationThreadProps = {
  projectId: string | number;
  auditId: string | number;
  sectionPath?: string | null;
  sourceRecommendationKey?: string | null;
  title: string;
  initialCount?: number;
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

export default function PortalAnnotationThread({
  projectId,
  auditId,
  sectionPath = null,
  sourceRecommendationKey = null,
  title,
  initialCount = 0,
}: PortalAnnotationThreadProps) {
  const { getToken, user } = useAuth();
  const [items, setItems] = useState<ReportAnnotation[]>([]);
  const [loading, setLoading] = useState(initialCount > 0);
  const [replyParentId, setReplyParentId] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access the portal thread.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadAnnotations = useCallback(async () => {
    if (initialCount <= 0) {
      setItems([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetchPortalAuditAnnotations(projectId, auditId, headers, {
        sectionPath,
        sourceRecommendationKey,
        page: 1,
        perPage: 50,
      });
      setItems(response.items);
    } catch (loadError) {
      toast.error(loadError instanceof Error ? loadError.message : "Failed to load portal thread.");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [auditId, getAuthHeaders, initialCount, projectId, sectionPath, sourceRecommendationKey]);

  useEffect(() => {
    void loadAnnotations();
  }, [loadAnnotations]);

  const handleReply = async (parentId: number, content: string) => {
    const previousItems = items;
    const optimisticReply: ReportAnnotation = {
      id: -Date.now(),
      audit_id: Number(auditId),
      project_id: Number(projectId),
      user_id: user?.id ? Number(user.id) : null,
      user_display_name: user?.name || user?.email?.split("@", 1)[0] || "You",
      parent_id: parentId,
      section_path: sectionPath,
      source_recommendation_key: sourceRecommendationKey,
      content,
      visibility: "client_visible",
      is_deleted: false,
      created_at: new Date().toISOString(),
      updated_at: null,
      can_edit: false,
      can_delete: false,
      replies: [],
    };
    const optimisticItems = previousItems.map((item) =>
      item.id === parentId ? { ...item, replies: [...item.replies, optimisticReply] } : item
    );
    setItems(optimisticItems);
    setBusyAction(`reply:${parentId}`);
    try {
      const headers = await getAuthHeaders();
      await createPortalAnnotationReply(
        projectId,
        auditId,
        {
          parent_id: parentId,
          section_path: sectionPath,
          source_recommendation_key: sourceRecommendationKey,
          content,
        },
        headers
      );
      setReplyParentId(null);
      toast.success("Reply sent.");
      await loadAnnotations();
    } catch (actionError) {
      setItems(previousItems);
      toast.error(actionError instanceof Error ? actionError.message : "Reply failed.");
    } finally {
      setBusyAction(null);
    }
  };

  if (loading) {
    return (
      <div className="mt-4 flex items-center gap-2 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading client-visible notes...
      </div>
    );
  }

  if (items.length === 0) {
    return null;
  }

  return (
    <div className="mt-4 rounded-4xl border border-white/10  p-4">
      <div className="flex items-center gap-2">
        <MessageSquareMore className="h-4 w-4 text-slate-300" />
        <p className="text-sm font-semibold text-white">{title} context</p>
      </div>

      <div className="mt-4 space-y-4">
        {items.map((annotation) => (
          <div key={annotation.id} className="rounded-4xl border  bg-black/20 p-4">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-sm font-semibold text-white">
                  {annotation.user_display_name || "Project team"}
                </p>
                <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
                  {formatDateTime(annotation.updated_at || annotation.created_at)}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setReplyParentId((current) => (current === annotation.id ? null : annotation.id))
                }
              >
                <Reply className="h-3.5 w-3.5" />
                Reply
              </Button>
            </div>

            <div className="prose prose-invert mt-3 max-w-none text-sm prose-p:leading-7 prose-p:text-slate-300 prose-strong:text-white">
              <ReactMarkdown skipHtml>{annotation.content}</ReactMarkdown>
            </div>

            {annotation.replies.length > 0 ? (
              <div className="mt-4 space-y-3 border-t  pt-4">
                {annotation.replies.map((reply) => (
                  <div key={reply.id} className="rounded border  bg-[#0c1624] px-4 py-3">
                    <p className="text-sm font-semibold text-white">
                      {reply.user_display_name || "Project team"}
                    </p>
                    <p className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">
                      {formatDateTime(reply.updated_at || reply.created_at)}
                    </p>
                    <div className="prose prose-invert mt-3 max-w-none text-sm prose-p:leading-7 prose-p:text-slate-300 prose-strong:text-white">
                      <ReactMarkdown skipHtml>{reply.content}</ReactMarkdown>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            {replyParentId === annotation.id ? (
              <div className="mt-4 border-t  pt-4">
                <AnnotationComposer
                  submitLabel="Send reply"
                  placeholder="Reply with client context..."
                  initialVisibility="client_visible"
                  showVisibilityToggle={false}
                  loading={busyAction === `reply:${annotation.id}`}
                  onCancel={() => setReplyParentId(null)}
                  onSubmit={(payload) => handleReply(annotation.id, payload.content)}
                />
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
