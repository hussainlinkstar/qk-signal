"use client";

import React, { useCallback, useState } from "react";
import {
  ShieldCheck,
  AlertTriangle,
  Database,
  Trash2,
  HardDrive,
  Activity,
  Info,
  Zap,
  Terminal,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { ClientSafeDate } from "@/lib/dateFormat";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import { Alert, AlertDescription } from "@/components/ui/alert";

type DataRetentionCleanupResponse = {
  executed_at: string;
  retention_days: number | null;
  strip_screenshots_after_days: number | null;
  audits_deleted: number;
  screenshots_redacted: number;
};

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4";

export default function AdminAuditRetentionPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [result, setResult] = useState<DataRetentionCleanupResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin cleanup.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const runCleanup = async () => {
    if (!isSignedIn) return;
    setIsConfirmOpen(true);
  };

  const confirmRunCleanup = async () => {
    setIsConfirmOpen(false);
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/data-retention/cleanup", {
        method: "POST",
        headers,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to run retention cleanup.");
      }
      const payload = (await response.json()) as DataRetentionCleanupResponse;
      setResult(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run retention cleanup.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      <DashboardPageIntro icon={Database} title="Data lifecycle">
        Enforce data retention policies, purge aged audit records and redact screenshots from legacy
        entries to maintain compliance.
      </DashboardPageIntro>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className={CARD}>
            <div className="flex items-start gap-5">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-(--r-md) bg-(--purple-s) text-(--purple)">
                <ShieldCheck size={22} />
              </div>
              <div className="flex-1">
                <h2 className={CARD_TITLE}>Run cleanup</h2>
                <p className="mt-2 mb-5 text-[13px] leading-[1.5] text-(--t-2)">
                  Triggers the server-side retention job. Audits exceeding the retention threshold
                  will be permanently deleted; screenshots older than the redaction window will be
                  stripped from remaining records.
                </p>

                <div className="flex items-center gap-4">
                  <Button
                    variant="primary"
                    onClick={runCleanup}
                    disabled={isLoading || isGuardLoading}
                  >
                    {isLoading ? (
                      <>
                        <Activity className="mr-2 animate-spin" size={16} />
                        Running...
                      </>
                    ) : (
                      <>
                        <Zap className="mr-2" size={16} />
                        Run Cleanup
                      </>
                    )}
                  </Button>

                  {!isAdmin && !isGuardLoading && (
                    <div className="flex items-center gap-2 font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--warn)">
                      <Terminal size={12} /> Admin access required
                    </div>
                  )}
                </div>
              </div>
            </div>

            {error && (
              <Alert variant="destructive" className="mt-6">
                <AlertTriangle />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </section>

          {result && (
            <section className={CARD}>
              <div className="mb-6 flex items-center justify-between border-b border-(--line) pb-4">
                <h2 className={CARD_TITLE}>Cleanup results</h2>
                <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) tabular-nums">
                  Executed: <ClientSafeDate date={result.executed_at} />
                </span>
              </div>

              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-4">
                  <div>
                    <p className={`${MICRO_LABEL} mb-2`}>Retention Threshold</p>
                    <div className="flex items-center gap-2">
                      <span className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
                        {result.retention_days ?? "∞"}
                      </span>
                      <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        days
                      </span>
                    </div>
                  </div>
                  <div>
                    <p className={`${MICRO_LABEL} mb-2`}>Screenshot Redaction Window</p>
                    <div className="flex items-center gap-2">
                      <span className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
                        {result.strip_screenshots_after_days ?? "∞"}
                      </span>
                      <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                        days
                      </span>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className={INSET}>
                    <div className="mb-1 flex items-center justify-between">
                      <span className={MICRO_LABEL}>Audits Deleted</span>
                      <Trash2 size={12} className="text-(--bad)" />
                    </div>
                    <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--bad) tabular-nums">
                      {result.audits_deleted}
                    </p>
                  </div>
                  <div className={INSET}>
                    <div className="mb-1 flex items-center justify-between">
                      <span className={MICRO_LABEL}>Screenshots Redacted</span>
                      <ShieldCheck size={12} className="text-(--good)" />
                    </div>
                    <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--good) tabular-nums">
                      {result.screenshots_redacted}
                    </p>
                  </div>
                </div>
              </div>
            </section>
          )}
        </div>

        <div className="space-y-6">
          <section className={CARD}>
            <h3 className={`${CARD_TITLE} mb-4 flex items-center gap-2`}>
              <Info size={14} className="text-(--warn)" /> Retention Policy
            </h3>
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <div className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-(--warn)" />
                <p className="text-[13px] leading-[1.5] text-(--t-2)">
                  Audits older than the <span className="text-(--t-1)">Retention Days</span>{" "}
                  threshold are permanently deleted from primary storage.
                </p>
              </div>
              <div className="flex items-start gap-3">
                <div className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-(--purple)" />
                <p className="text-[13px] leading-[1.5] text-(--t-2)">
                  Screenshots are stripped from records after the{" "}
                  <span className="text-(--t-1)">Redaction Window</span> while the audit log entry
                  is preserved.
                </p>
              </div>
            </div>
          </section>

          <section className={CARD}>
            <h3 className={`${CARD_TITLE} mb-4 flex items-center gap-2`}>
              <HardDrive size={14} className="text-(--purple)" /> Storage Status
            </h3>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-(--good)" />
                <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-2)">
                  Encryption Active
                </span>
              </div>
              <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                Ready
              </span>
            </div>
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-(--line-2)">
              <div className="h-full w-[65%] bg-(--purple)" />
            </div>
          </section>
        </div>
      </div>

      {/* Confirm dialog */}
      <Modal open={isConfirmOpen} onClose={() => setIsConfirmOpen(false)}>
        <div className="space-y-4 p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-(--r-md) bg-(--warn-s) text-(--warn)">
              <AlertTriangle size={20} />
            </div>
            <h2 className={CARD_TITLE}>Confirm cleanup</h2>
          </div>
          <p className="text-[13px] leading-[1.5] text-(--t-2)">
            This will permanently delete audit records beyond the retention threshold and strip
            screenshots from eligible entries. This action cannot be undone.
          </p>
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setIsConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={confirmRunCleanup} disabled={isLoading}>
              Confirm & Run
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
