"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/custom-auth";
import {
  AlertTriangle,
  ArrowLeft,
  Eye,
  EyeOff,
  Trash2,
  Wand2,
  ShieldCheck,
  Globe,
  User,
  Activity,
  Clock,
  Zap,
  Layers,
  FileJson,
  Workflow,
} from "lucide-react";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { ClientSafeDate } from "@/lib/dateFormat";
import { cx } from "@/components/ui/utils";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";

type AdminAuditDetail = {
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
  subscription_type: string | null;
  credits_used: number | null;
  credits_remaining: number;
  created_at: string;
  sanitized_at: string | null;
  full_report: Record<string, unknown> | null;
  has_screenshot: boolean;
};

type AdminAuditSanitizeResponse = {
  id: number;
  sanitized_at: string | null;
  screenshot_removed: boolean;
};

/* -------------------------------------------------------------------------- */
/*  Design tokens                                                              */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 mb-5 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border border-(--line) bg-(--paper) p-4";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const BACKLINK =
  "flex w-fit items-center gap-2 font-(family-name:--mono) text-[11.5px] tracking-[0.06em] text-(--t-3) transition-colors hover:text-(--t-1)";

const formatScore = (score: number) => {
  const normalized = score <= 1 ? score * 100 : score;
  return Math.round(normalized);
};

const formatAuditLabel = (value: string | null | undefined) =>
  value ? value.replace(/_/g, " ") : "not recorded";

const getGroundingChipClass = (profile: string | null | undefined) => {
  if (!profile) return `${CHIP} text-(--t-3) bg-(--paper)`;
  if (profile === "shadow_dual_track") return `${CHIP} text-(--purple) bg-(--purple-s)`;
  if (profile.includes("fallback")) return `${CHIP} text-(--warn) bg-(--warn-s)`;
  return `${CHIP} text-(--purple) bg-(--purple-s)`;
};

const getDualTrackChipClass = (isEnabled: boolean) =>
  isEnabled ? `${CHIP} text-(--good) bg-(--good-s)` : `${CHIP} text-(--t-3) bg-(--paper)`;

// --- UI Components ---

const DetailRow = ({
  label,
  value,
  icon: Icon,
  subValue,
}: {
  label: string;
  value: React.ReactNode;
  icon?: React.ComponentType<{ size?: number | string; className?: string }>;
  subValue?: string;
}) => (
  <div className={`${INSET} flex flex-col gap-1.5`}>
    <p className={`${MICRO_LABEL} flex items-center gap-2`}>
      {Icon && <Icon size={12} />}
      {label}
    </p>
    <div className="wrap-break-word text-sm font-semibold text-(--t-1)">{value}</div>
    {subValue && <div className={MONO_META}>{subValue}</div>}
  </div>
);

export default function AdminAuditDetailPage() {
  const params = useParams();
  const router = useRouter();
  const auditId = Array.isArray(params?.auditId) ? params.auditId[0] : params?.auditId;

  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [audit, setAudit] = useState<AdminAuditDetail | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [includeScreenshot, setIncludeScreenshot] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const [confirmAction, setConfirmAction] = useState<"sanitize" | "delete" | null>(null);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access audit records.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadAudit = useCallback(async () => {
    if (!auditId || !isSignedIn) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams();
      if (includeScreenshot) params.set("include_screenshot", "true");

      const response = await fetch(`/api/admin/audits/${auditId}?${params.toString()}`, {
        headers,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load audit details.");
      }
      const payload = (await response.json()) as AdminAuditDetail;
      setAudit(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load audit details.");
    } finally {
      setIsLoading(false);
    }
  }, [auditId, getAuthHeaders, includeScreenshot, isSignedIn]);

  useEffect(() => {
    loadAudit();
  }, [loadAudit]);

  const handleSanitize = async () => {
    if (!auditId || actionLoading) return;
    setConfirmAction("sanitize");
  };

  const executeSanitize = async () => {
    setActionLoading(true);
    setActionMessage("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/audits/${auditId}/sanitize`, {
        method: "POST",
        headers,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to sanitize the audit.");
      }
      const payload = (await response.json()) as AdminAuditSanitizeResponse;
      setActionMessage(payload.screenshot_removed ? "Screenshot removed." : "No screenshot found.");
      await loadAudit();
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Unable to sanitize the audit.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!auditId || actionLoading) return;
    setConfirmAction("delete");
  };

  const executeDelete = async () => {
    setActionLoading(true);
    setActionMessage("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/audits/${auditId}`, {
        method: "DELETE",
        headers,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to delete the audit.");
      }
      setActionMessage("Audit deleted.");
      router.push("/admin/audit-application");
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Unable to delete the audit.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleConfirmAction = async () => {
    const action = confirmAction;
    setConfirmAction(null);
    if (!action) return;

    if (action === "sanitize") {
      await executeSanitize();
      return;
    }

    await executeDelete();
  };

  const rawJson = useMemo(() => {
    if (!audit?.full_report) return "";
    return JSON.stringify(audit.full_report, null, 2);
  }, [audit?.full_report]);

  const targetLabel = useMemo(
    () => audit?.target_name || audit?.target_url || audit?.url || "Loading...",
    [audit?.target_name, audit?.target_url, audit?.url]
  );
  const hasRuntimeMetadata = useMemo(
    () =>
      Boolean(
        audit?.grounding_profile ||
        audit?.fallback_reason ||
        audit?.dual_track_rollout_mode ||
        audit?.dual_track_execution_mode ||
        audit?.track_a_claim_count != null ||
        audit?.track_b_claim_count != null ||
        audit?.requested_tier
      ),
    [
      audit?.dual_track_execution_mode,
      audit?.dual_track_rollout_mode,
      audit?.fallback_reason,
      audit?.grounding_profile,
      audit?.requested_tier,
      audit?.track_a_claim_count,
      audit?.track_b_claim_count,
    ]
  );
  const hasDebateTrace = useMemo(() => {
    const metadata =
      audit?.full_report &&
      typeof audit.full_report === "object" &&
      !Array.isArray(audit.full_report)
        ? (audit.full_report as Record<string, unknown>)["metadata"]
        : null;
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return false;
    const debate = (metadata as Record<string, unknown>).debate;
    if (!debate || typeof debate !== "object" || Array.isArray(debate)) return false;
    return Boolean((debate as Record<string, unknown>).enabled);
  }, [audit?.full_report]);
  const busy = isLoading || actionLoading || isGuardLoading;

  const { setHeader } = useWorkspacePageHeader();
  const actionsRef = useRef({ handleSanitize, handleDelete });
  actionsRef.current = { handleSanitize, handleDelete };
  useEffect(() => {
    setHeader({
      actions: (
        <>
          {hasDebateTrace && (
            <Link href={`/admin/audit-application/${auditId}/debate-trace`}>
              <Button variant="ghost" size="sm">
                <Workflow size={14} />
                <span className="max-sm:hidden">View debate trace</span>
              </Button>
            </Link>
          )}
          <Button
            onClick={() => void actionsRef.current.handleSanitize()}
            loading={busy}
            variant="ghost"
            size="sm"
            aria-label="Remove screenshot"
            title="Remove screenshot"
          >
            <Wand2 size={14} />
            <span className="max-sm:hidden">Remove screenshot</span>
          </Button>
          <Button
            onClick={() => void actionsRef.current.handleDelete()}
            loading={busy}
            variant="danger"
            size="sm"
            aria-label="Delete record"
            title="Delete record"
          >
            <Trash2 size={14} />
            <span className="max-sm:hidden">Delete record</span>
          </Button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [auditId, busy, hasDebateTrace, setHeader]);

  return (
    <>
      {/* Back link */}
      <Link href="/admin/audit-application" className={BACKLINK}>
        <ArrowLeft size={14} /> Back to audit history
      </Link>

      {/* Header & actions */}
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <DashboardPageIntro icon={Layers} title={`Audit #${auditId}`}>
          Reviewing audit configuration and results for target:{" "}
          <span className="font-semibold text-(--t-1)">{targetLabel}</span>
        </DashboardPageIntro>
      </div>

      {/* Status messages */}
      {error && (
        <Alert variant="destructive">
          <AlertTriangle size={16} />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {actionMessage && (
        <Alert>
          <ShieldCheck size={16} />
          <AlertDescription>{actionMessage}</AlertDescription>
        </Alert>
      )}

      {isLoading && !audit ? (
        <AdminCardSkeleton cards={4} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Core parameters */}
          <div className="space-y-6 lg:col-span-2">
            <section className={WSEC}>
              <h3 className={SEC_TITLE}>
                <Activity size={14} className="text-(--purple)" />
                Audit configuration
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <DetailRow
                  label="Target"
                  value={targetLabel}
                  icon={Globe}
                  subValue={`Type: ${formatAuditLabel(audit?.audit_target_type)}`}
                />
                <DetailRow
                  label="Target URL"
                  value={audit?.target_url || audit?.url}
                  icon={Globe}
                  subValue={audit?.target_name ? `Label: ${audit.target_name}` : undefined}
                />
                <DetailRow
                  label="User"
                  value={audit?.user_email}
                  icon={User}
                  subValue={`User ID: ${audit?.user_id}`}
                />

                <div className={`${INSET} flex items-center justify-between`}>
                  <div className="space-y-1">
                    <p className={MICRO_LABEL}>Audit scores</p>
                    <div className="mt-2 flex gap-2">
                      <span className={`${CHIP} text-(--link) bg-(--purple-s)`}>
                        AI visibility {formatScore(audit?.geo_score || 0)}
                      </span>
                      <span className={`${CHIP} text-(--purple) bg-(--purple-s)`}>
                        SEO {formatScore(audit?.seo_score || 0)}
                      </span>
                      <span className={`${CHIP} text-(--warn) bg-(--warn-s)`}>
                        AI answers {formatScore(audit?.aeo_score || 0)}
                      </span>
                    </div>
                  </div>
                </div>

                <DetailRow
                  label="AI model"
                  value={`${audit?.provider || "generic"} / ${audit?.tier || "standard"}`}
                  icon={Zap}
                />
                <DetailRow
                  label="Requested tier"
                  value={formatAuditLabel(audit?.requested_tier ?? audit?.tier)}
                  icon={Layers}
                  subValue="Operator-visible execution intent"
                />
                <DetailRow
                  label="Compute usage"
                  value={`Used: ${audit?.credits_used ?? 0} credits`}
                  icon={Activity}
                  subValue={`Remaining: ${audit?.credits_remaining ?? 0}`}
                />
                <DetailRow
                  label="Subscription plan"
                  value={
                    audit?.subscription_type
                      ? audit.subscription_type.replace(/_/g, " ")
                      : "standard"
                  }
                  icon={ShieldCheck}
                  subValue="Plan level"
                />
                <DetailRow
                  label="Created at"
                  value={<ClientSafeDate date={audit?.created_at || new Date()} />}
                  icon={Clock}
                  subValue="Audit created"
                />
              </div>
            </section>

            <section className={WSEC}>
              <h3 className={SEC_TITLE}>
                <ShieldCheck size={14} className="text-(--purple)" />
                Dual-track grounding runtime
              </h3>

              <div className="flex flex-wrap gap-2">
                <span className={getGroundingChipClass(audit?.grounding_profile)}>
                  <Layers size={10} />
                  {formatAuditLabel(audit?.grounding_profile)}
                </span>
                <span
                  className={getDualTrackChipClass(Boolean(audit?.dual_track_grounding_enabled))}
                >
                  <ShieldCheck size={10} />
                  {audit?.dual_track_grounding_enabled
                    ? "Dual-track enabled"
                    : "Dual-track disabled"}
                </span>
                <span className={`${CHIP} text-(--t-2) bg-(--paper)`}>
                  <Zap size={10} />
                  Requested {formatAuditLabel(audit?.requested_tier ?? audit?.tier)}
                </span>
              </div>

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <DetailRow
                  label="Fallback reason"
                  value={formatAuditLabel(audit?.fallback_reason)}
                  icon={AlertTriangle}
                  subValue="Safe-fail audit fallback marker"
                />
                <DetailRow
                  label="Rollout mode"
                  value={formatAuditLabel(audit?.dual_track_rollout_mode)}
                  icon={Layers}
                  subValue="Server-side rollout policy"
                />
                <DetailRow
                  label="Execution mode"
                  value={formatAuditLabel(audit?.dual_track_execution_mode)}
                  icon={Zap}
                  subValue="Effective runtime behavior"
                />
                <DetailRow
                  label="Per-track claims"
                  value={`Track A: ${audit?.track_a_claim_count ?? 0} / Track B: ${audit?.track_b_claim_count ?? 0}`}
                  icon={Activity}
                  subValue="Persisted integrity summary counts"
                />
              </div>

              {!hasRuntimeMetadata && (
                <div className={`${INSET} mt-5`}>
                  <p className={MONO_META}>
                    Legacy or single-track audit: dual-track runtime metadata was not persisted for
                    this run.
                  </p>
                </div>
              )}
            </section>

            {showRaw && (
              <section className="overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)">
                <div className="flex items-center justify-between border-b border-(--line) px-[22px] py-[14px]">
                  <h4 className={`${MONO_META} m-0 flex items-center gap-2`}>
                    <FileJson size={14} /> Raw results data
                  </h4>
                  <button
                    onClick={() => setShowRaw(false)}
                    className={`${MONO_META} transition-colors hover:text-(--t-1)`}
                  >
                    Close view
                  </button>
                </div>
                <div className="max-h-[600px] overflow-y-auto bg-(--paper) p-6">
                  <pre className="font-(family-name:--mono) text-[11px] leading-relaxed whitespace-pre-wrap text-(--t-2)">
                    {rawJson}
                  </pre>
                </div>
              </section>
            )}
          </div>

          {/* System controls */}
          <div className="space-y-6">
            <section className={WSEC}>
              <h3 className={SEC_TITLE}>
                <ShieldCheck size={14} className="text-(--purple)" />
                Security controls
              </h3>

              <div className="space-y-5">
                <label className={`${INSET} flex cursor-pointer items-center gap-3`}>
                  <input
                    type="checkbox"
                    checked={includeScreenshot}
                    onChange={(e) => setIncludeScreenshot(e.target.checked)}
                    className="h-4 w-4 accent-(--purple)"
                  />
                  <div className="flex-1">
                    <p className="text-[13px] font-semibold text-(--t-1)">Full results mode</p>
                    <p className="text-[11px] text-(--t-3)">Include screenshot image data</p>
                  </div>
                </label>

                <Button onClick={() => setShowRaw(!showRaw)} variant="ghost" className="w-full">
                  {showRaw ? <EyeOff size={14} /> : <Eye size={14} />}
                  {showRaw ? "Hide raw data" : "View raw data"}
                </Button>

                <div className={`${INSET} space-y-2`}>
                  <p className={MICRO_LABEL}>Sanitization status</p>
                  <div className="flex items-center gap-2">
                    <div
                      className={cx(
                        "h-1.5 w-1.5 rounded-full",
                        audit?.sanitized_at ? "bg-(--good)" : "bg-(--line-2)"
                      )}
                    />
                    <span className="text-xs font-semibold text-(--t-1)">
                      {audit?.sanitized_at ? "Sanitized" : "Original data"}
                    </span>
                  </div>
                  {audit?.sanitized_at && (
                    <p className="mt-1 text-[11px] text-(--t-3)">
                      Processed: <ClientSafeDate date={audit.sanitized_at} />
                    </p>
                  )}
                </div>

                <p className="text-center text-[11px] text-(--t-3)">
                  Permanently remove screenshot data from this audit record.
                </p>
              </div>
            </section>

            <section className="rounded-(--r) border border-(--bad) bg-(--bad-s) px-[22px] py-[18px]">
              <p className={`${MICRO_LABEL} text-(--bad)`}>Danger zone</p>
              <p className="mt-2 text-xs leading-relaxed text-(--t-2)">
                Deleting this record will permanently erase all assessment data and scores from the
                system.
              </p>
              <Button onClick={handleDelete} variant="danger" className="mt-4 w-full">
                Permanent deletion
              </Button>
            </section>
          </div>
        </div>
      )}

      {!isAdmin && !isGuardLoading && (
        <Alert variant="warning">
          <Activity className="h-4 w-4" />
          <AlertDescription>
            Access denied: admin override required for viewing audit records.
          </AlertDescription>
        </Alert>
      )}

      <Modal
        open={confirmAction !== null}
        onClose={() => setConfirmAction(null)}
        panelClassName="w-full max-w-lg"
        ariaLabelledby="audit-confirm-title"
      >
        <div className="space-y-5">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-(--r-md) bg-(--bad-s) text-(--bad)">
              <AlertTriangle size={18} />
            </div>
            <div>
              <h2
                id="audit-confirm-title"
                className="m-0 font-(family-name:--disp) text-[17px] font-bold tracking-[-0.01em] text-(--t-1)"
              >
                {confirmAction === "sanitize" ? "Confirm screenshot removal" : "Confirm deletion"}
              </h2>
              <p className="mt-1 text-sm text-(--t-2)">
                {confirmAction === "sanitize"
                  ? "This action will permanently delete the screenshot associated with this audit."
                  : "This permanently deletes the audit record and all related data."}
              </p>
            </div>
          </div>

          <p className={`${INSET} text-xs text-(--t-2)`}>
            Please confirm that you want to continue.
          </p>

          <div className="flex items-center justify-end gap-3">
            <Button variant="ghost" onClick={() => setConfirmAction(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={handleConfirmAction} disabled={actionLoading}>
              {confirmAction === "sanitize" ? "Confirm removal" : "Confirm delete"}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
