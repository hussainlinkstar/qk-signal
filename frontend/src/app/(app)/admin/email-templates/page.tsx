"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Search,
  RefreshCcw,
  Send,
  Eye,
  Monitor,
  Smartphone,
  LayoutTemplate,
  ChevronRight,
  Code2,
  X,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import Button from "@/components/ui/Button";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import { NativeSelect } from "@/components/ui/native-select";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { toast } from "sonner";

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type TemplateDef = {
  key: string;
  subject: string;
  html_template: string;
  category: string;
};

type TemplateListResponse = {
  templates: TemplateDef[];
  categories: string[];
  total: number;
};

type PreviewResponse = {
  key: string;
  subject: string;
  html: string;
  text: string;
  category: string;
  html_template: string;
};

type TestSendResponse = {
  status: string;
  outbox_id: number;
  to_email: string;
  subject: string;
};

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const WINPUT_SM =
  "field-focus-ring h-8 rounded-(--r-md) border border-(--line) bg-(--paper) px-[10px] text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border border-(--line) bg-(--paper) px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

const CATEGORY_CHIP: Record<string, string> = {
  account_notification: `${CHIP} text-(--purple) bg-(--purple-s)`,
  billing: `${CHIP} text-(--purple) bg-(--purple-s)`,
  audit_notification: `${CHIP} text-(--purple) bg-(--purple-s)`,
  system_alert: `${CHIP} text-(--warn) bg-(--warn-s)`,
  alert_notification: `${CHIP} text-(--bad) bg-(--bad-s)`,
  report_delivery: `${CHIP} text-(--good) bg-(--good-s)`,
  collaboration: `${CHIP} text-(--purple) bg-(--purple-s)`,
  trial_invitation: `${CHIP} text-(--warn) bg-(--warn-s)`,
  trial_feedback: `${CHIP} text-(--warn) bg-(--warn-s)`,
  lead_notification: `${CHIP} text-(--good) bg-(--good-s)`,
};

const CATEGORY_LABELS: Record<string, string> = {
  account_notification: "Account",
  billing: "Billing",
  audit_notification: "Audit",
  system_alert: "System",
  alert_notification: "Alert",
  report_delivery: "Report",
  collaboration: "Collab",
  trial_invitation: "Trial",
  trial_feedback: "Feedback",
  lead_notification: "Lead",
};

function CategoryBadge({ category }: { category: string }) {
  const chip = CATEGORY_CHIP[category] ?? `${CHIP} text-(--t-2) bg-(--line-2)`;
  const label = CATEGORY_LABELS[category] ?? category.replace(/_/g, " ");
  return <span className={chip}>{label}</span>;
}

/* -------------------------------------------------------------------------- */
/*  Page Component                                                             */
/* -------------------------------------------------------------------------- */

export default function AdminEmailTemplatesPage() {
  const { getToken, isSignedIn, user } = useAuth();
  const { isAdmin } = useAdminAccess();

  /* ── state ── */
  const [templates, setTemplates] = useState<TemplateDef[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewSubject, setPreviewSubject] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);

  const [viewMode, setViewMode] = useState<"desktop" | "mobile">("desktop");
  const [showContextEditor, setShowContextEditor] = useState(false);
  const [contextJson, setContextJson] = useState("{}");
  const [contextError, setContextError] = useState("");

  const [testEmail, setTestEmail] = useState(user?.email ?? "");
  const [testSending, setTestSending] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement>(null);

  /* ── auth headers ── */
  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("You must be signed in.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  /* ── load template list ── */
  const loadTemplates = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/email-templates", { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load templates.");
      }
      const data: TemplateListResponse = await response.json();
      setTemplates(data.templates);
      setCategories(data.categories);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load templates.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  /* ── load default context on first mount ── */
  useEffect(() => {
    if (!isSignedIn) return;
    (async () => {
      try {
        const headers = await getAuthHeaders();
        const res = await fetch("/api/admin/email-templates/default-context", { headers });
        if (res.ok) {
          const data = await res.json();
          setContextJson(JSON.stringify(data.context, null, 2));
        }
      } catch {
        /* non-critical */
      }
    })();
  }, [getAuthHeaders, isSignedIn]);

  /* ── prefill test email ── */
  useEffect(() => {
    if (user?.email && !testEmail) setTestEmail(user.email);
  }, [user?.email, testEmail]);

  /* ── load preview ── */
  const loadPreview = useCallback(
    async (templateKey: string, ctx?: Record<string, unknown>) => {
      setPreviewLoading(true);
      setPreviewHtml(null);
      setPreviewSubject("");
      try {
        const headers = await getAuthHeaders();
        let parsedCtx: Record<string, unknown> = {};
        if (ctx) {
          parsedCtx = ctx;
        } else {
          try {
            parsedCtx = JSON.parse(contextJson);
          } catch {
            /* use empty context */
          }
        }
        const response = await fetch(`/api/admin/email-templates/${templateKey}/preview`, {
          method: "POST",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ context: parsedCtx }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Preview failed.");
        }
        const data: PreviewResponse = await response.json();
        setPreviewHtml(data.html);
        setPreviewSubject(data.subject);
      } catch (err: unknown) {
        toast.error(err instanceof Error ? err.message : "Preview failed.");
      } finally {
        setPreviewLoading(false);
      }
    },
    [getAuthHeaders, contextJson]
  );

  /* ── select template ── */
  const handleSelect = useCallback(
    (key: string) => {
      setSelectedKey(key);
      loadPreview(key);
    },
    [loadPreview]
  );

  /* ── refresh preview with edited context ── */
  const handleRefreshPreview = useCallback(() => {
    if (!selectedKey) return;
    setContextError("");
    try {
      JSON.parse(contextJson);
    } catch {
      setContextError("Invalid JSON");
      return;
    }
    loadPreview(selectedKey);
  }, [selectedKey, contextJson, loadPreview]);

  /* ── test send ── */
  const handleTestSend = useCallback(async () => {
    if (!selectedKey || !testEmail.trim()) return;
    setTestSending(true);
    try {
      const headers = await getAuthHeaders();
      let parsedCtx: Record<string, unknown> = {};
      try {
        parsedCtx = JSON.parse(contextJson);
      } catch {
        /* use empty */
      }
      const response = await fetch(`/api/admin/email-templates/${selectedKey}/test-send`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ to_email: testEmail.trim(), context: parsedCtx }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Test send failed.");
      }
      const data: TestSendResponse = await response.json();
      toast.success(`Queued test email to ${data.to_email}`);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Test send failed.");
    } finally {
      setTestSending(false);
    }
  }, [selectedKey, testEmail, contextJson, getAuthHeaders]);

  /* ── filtered list ── */
  const filtered = useMemo(() => {
    let list = templates;
    if (categoryFilter) list = list.filter((t) => t.category === categoryFilter);
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (t) =>
          t.key.toLowerCase().includes(q) ||
          t.subject.toLowerCase().includes(q) ||
          t.html_template.toLowerCase().includes(q)
      );
    }
    return list;
  }, [templates, categoryFilter, searchQuery]);

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: isAdmin ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void loadTemplates()}
          disabled={isLoading}
          aria-label="Refresh"
          title="Refresh"
          className="h-8 w-8 p-0"
        >
          <RefreshCcw size={14} className={isLoading ? "animate-spin" : ""} />
        </Button>
      ) : null,
    });
    return () => setHeader(null);
  }, [isAdmin, isLoading, loadTemplates, setHeader]);

  /* ── render ── */
  if (!isAdmin) {
    return <AdminInlineError message="Admin privileges required to view email templates." />;
  }

  return (
    <>
      {/* Header */}
      <DashboardPageIntro icon={LayoutTemplate} title="Email templates">
        Preview, customize context, and test-send {templates.length} email templates.
      </DashboardPageIntro>

      {error && <AdminInlineError message={error} onRetry={loadTemplates} />}

      {/* Main layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[340px_1fr]">
        {/* Left: Template list */}
        <section className="overflow-hidden rounded-(--r-md) border border-(--line) bg-(--panel)">
          {/* Search & filter */}
          <div className="space-y-3 border-b border-(--line) p-4">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-(--t-3)"
              />
              <input
                type="text"
                placeholder="Search templates..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={`${WINPUT_SM} w-full pl-8`}
              />
            </div>
            <NativeSelect
              variant="auth"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="h-8 w-full text-[12.5px]"
              aria-label="Category filter"
            >
              <option value="">All categories ({templates.length})</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>
                  {(CATEGORY_LABELS[cat] ?? cat).replace(/_/g, " ")} (
                  {templates.filter((t) => t.category === cat).length})
                </option>
              ))}
            </NativeSelect>
          </div>

          {/* Template list */}
          <div className="max-h-[calc(100vh-340px)] overflow-y-auto">
            {isLoading ? (
              <p className={`${MONO_META} py-12 text-center`}>Loading templates...</p>
            ) : filtered.length === 0 ? (
              <p className="py-12 text-center text-sm text-(--t-2)">No templates found.</p>
            ) : (
              <ul className="divide-y divide-(--line-2)">
                {filtered.map((tmpl) => (
                  <li key={tmpl.key}>
                    <button
                      onClick={() => handleSelect(tmpl.key)}
                      className={`w-full px-4 py-3 text-left transition-colors hover:bg-(--paper) ${
                        selectedKey === tmpl.key
                          ? "border-l-2 border-l-(--purple) bg-(--paper)"
                          : ""
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-(--t-1)">{tmpl.key}</p>
                          <p className="mt-0.5 truncate text-xs text-(--t-3)">{tmpl.subject}</p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <CategoryBadge category={tmpl.category} />
                          <ChevronRight size={14} className="text-(--t-3)" />
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Right: Preview panel */}
        <div className="space-y-4">
          {!selectedKey ? (
            <div className={`${WSEC} flex flex-col items-center justify-center py-24`}>
              <LayoutTemplate size={48} className="text-(--t-3) opacity-30" />
              <p className="mt-4 text-sm text-(--t-2)">Select a template to preview</p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Preview toolbar */}
              <div className={WSEC}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className={MICRO_LABEL}>Subject</p>
                    <p className="mt-0.5 truncate text-sm font-semibold text-(--t-1)">
                      {previewSubject || "(loading...)"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {/* Viewport toggle */}
                    <div className="flex overflow-hidden rounded-(--r-sm) border border-(--line)">
                      <button
                        onClick={() => setViewMode("desktop")}
                        className={`px-2.5 py-1.5 text-xs transition-colors ${
                          viewMode === "desktop"
                            ? "bg-(--purple-s) text-(--purple)"
                            : "text-(--t-3) hover:bg-(--paper)"
                        }`}
                        title="Desktop view"
                        aria-label="Desktop view"
                      >
                        <Monitor size={14} />
                      </button>
                      <button
                        onClick={() => setViewMode("mobile")}
                        className={`px-2.5 py-1.5 text-xs transition-colors ${
                          viewMode === "mobile"
                            ? "bg-(--purple-s) text-(--purple)"
                            : "text-(--t-3) hover:bg-(--paper)"
                        }`}
                        title="Mobile view"
                        aria-label="Mobile view"
                      >
                        <Smartphone size={14} />
                      </button>
                    </div>
                    {/* Context editor toggle */}
                    <button
                      onClick={() => setShowContextEditor(!showContextEditor)}
                      className={`flex items-center gap-1 rounded-(--r-sm) border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                        showContextEditor
                          ? "border-(--purple) bg-(--purple-s) text-(--purple)"
                          : "border-(--line) text-(--t-3) hover:bg-(--paper)"
                      }`}
                      title="Edit template context"
                    >
                      <Code2 size={14} />
                      Context
                    </button>
                    {/* Refresh preview */}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleRefreshPreview}
                      disabled={previewLoading}
                    >
                      <Eye size={14} />
                      Preview
                    </Button>
                  </div>
                </div>
              </div>

              {/* Context editor (collapsible) */}
              {showContextEditor && (
                <div className={`${WSEC} space-y-3`}>
                  <div className="flex items-center justify-between">
                    <p className={MICRO_LABEL}>Template context (JSON)</p>
                    <button
                      onClick={() => setShowContextEditor(false)}
                      aria-label="Close context editor"
                      className="text-(--t-3) hover:text-(--t-1)"
                    >
                      <X size={14} />
                    </button>
                  </div>
                  <textarea
                    value={contextJson}
                    onChange={(e) => {
                      setContextJson(e.target.value);
                      setContextError("");
                    }}
                    rows={12}
                    spellCheck={false}
                    className="field-focus-ring w-full resize-y rounded-(--r-md) border border-(--line) bg-(--paper) p-3 font-(family-name:--mono) text-xs text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]"
                  />
                  {contextError && <p className="text-xs text-(--bad)">{contextError}</p>}
                  <div className="flex justify-end">
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleRefreshPreview}
                      disabled={previewLoading}
                    >
                      Apply & preview
                    </Button>
                  </div>
                </div>
              )}

              {/* Email preview iframe */}
              <div className="overflow-hidden rounded-(--r-md) border border-(--line) bg-(--panel)">
                <div
                  className="mx-auto transition-all duration-300"
                  style={{ maxWidth: viewMode === "mobile" ? 375 : "100%" }}
                >
                  {previewLoading ? (
                    <p className={`${MONO_META} py-24 text-center`}>Rendering preview...</p>
                  ) : previewHtml ? (
                    <iframe
                      ref={iframeRef}
                      srcDoc={previewHtml}
                      sandbox="allow-same-origin"
                      title="Email preview"
                      className="w-full border-0 bg-white"
                      style={{ minHeight: 600 }}
                      onLoad={() => {
                        const iframe = iframeRef.current;
                        if (iframe?.contentDocument?.body) {
                          const height = iframe.contentDocument.body.scrollHeight;
                          iframe.style.height = `${Math.max(600, height + 32)}px`;
                        }
                      }}
                    />
                  ) : (
                    <div className="flex items-center justify-center py-24 text-sm text-(--t-2)">
                      Click &quot;Preview&quot; to render this template.
                    </div>
                  )}
                </div>
              </div>

              {/* Test send bar */}
              <div className={WSEC}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                  <div className="flex-1">
                    <label className={MICRO_LABEL}>Send test email to</label>
                    <input
                      type="email"
                      value={testEmail}
                      onChange={(e) => setTestEmail(e.target.value)}
                      placeholder="admin@example.com"
                      className={`${WINPUT} mt-1`}
                    />
                  </div>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleTestSend}
                    loading={testSending}
                    loadingText="Sending..."
                    disabled={!testEmail.trim() || !selectedKey}
                  >
                    <Send size={14} />
                    Send test
                  </Button>
                </div>
                <p className="mt-2 text-[11px] text-(--t-3)">
                  Subject will be prefixed with [TEST]. Email is queued to the outbox and sent by
                  the email worker.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
