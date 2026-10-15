"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { Settings, ExternalLink, RefreshCcw, Layout, Database, AlertTriangle } from "lucide-react";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import Button from "@/components/ui/Button";
import SelectField from "@/components/ui/SelectField";
import { Alert, AlertDescription } from "@/components/ui/alert";

const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";

type OperationStatus = {
  fallback_model_enabled: boolean;
  pricing_v2_enabled: boolean;
  credit_engine_v2_enabled: boolean;
  pricing_v2_shadow_mode: boolean;
  cache_refresh_requested_at: string | null;
  report_retention_days: number;
};

export default function AdminGeneralSettingsPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [operations, setOperations] = useState<OperationStatus | null>(null);
  const [retentionDraft, setRetentionDraft] = useState("30");
  const [isLoading, setIsLoading] = useState(false);
  const [isSavingRetention, setIsSavingRetention] = useState(false);
  const [error, setError] = useState("");
  const [retentionMessage, setRetentionMessage] = useState("");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin settings.");
    }
    return {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    };
  }, [getToken]);

  const loadSnapshot = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    setRetentionMessage("");
    try {
      const headers = await getAuthHeaders();
      const operationsRes = await fetch("/api/admin/operations", { headers });
      if (!operationsRes.ok) {
        throw new Error("Unable to load general settings snapshot.");
      }

      const operationsPayload = (await operationsRes.json()) as OperationStatus;
      setOperations(operationsPayload);
      setRetentionDraft(String(operationsPayload.report_retention_days ?? 30));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load settings snapshot.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadSnapshot();
  }, [loadSnapshot]);

  const controlsDisabled = !isAdmin || isGuardLoading || isLoading || isSavingRetention;

  const handleSaveRetention = useCallback(async () => {
    if (!isSignedIn) {
      return;
    }
    setError("");
    setRetentionMessage("");
    setIsSavingRetention(true);
    try {
      const headers = await getAuthHeaders();
      const parsedDays = Number(retentionDraft);
      const response = await fetch("/api/admin/operations/report-retention", {
        method: "POST",
        headers,
        body: JSON.stringify({ days: parsedDays }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to update report retention.");
      }
      const payload = (await response.json()) as OperationStatus;
      setOperations(payload);
      setRetentionDraft(String(payload.report_retention_days));
      setRetentionMessage("Report retention policy saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update report retention.");
    } finally {
      setIsSavingRetention(false);
    }
  }, [getAuthHeaders, isSignedIn, retentionDraft]);

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void loadSnapshot()}
          disabled={controlsDisabled}
          aria-label="Refresh status"
          title="Refresh status"
          className="h-8 w-8 p-0"
        >
          <RefreshCcw size={14} className={isLoading ? "animate-spin" : ""} />
        </Button>
      ),
    });
    return () => setHeader(null);
  }, [controlsDisabled, isLoading, loadSnapshot, setHeader]);

  return (
    <>
      <DashboardPageIntro icon={Settings} title="System settings">
        Manage global platform settings and system policies.
      </DashboardPageIntro>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <section className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
        <div className={INSET}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-xl">
              <p className={MICRO_LABEL}>Report Retention</p>
              <h3 className="mt-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                Complex PDF retention window
              </h3>
              <p className="mt-2 text-[13px] leading-[1.5] text-(--t-2)">
                Generated report files are automatically removed after this window and report jobs
                are marked as expired.
              </p>
            </div>
            <div className="flex w-full max-w-md flex-col gap-3">
              <SelectField
                label="Retention period"
                variant="auth"
                value={retentionDraft}
                onChange={(event) => setRetentionDraft(event.target.value)}
                disabled={controlsDisabled}
              >
                <option value="30">30 days (1 month)</option>
                <option value="60">60 days (2 months)</option>
                <option value="90">90 days (3 months)</option>
              </SelectField>
              <div className="flex items-center gap-3">
                <Button
                  variant="primary"
                  onClick={handleSaveRetention}
                  loading={isSavingRetention}
                  loadingText="Saving"
                  disabled={controlsDisabled}
                >
                  Save retention
                </Button>
                {operations ? (
                  <span className="text-xs text-(--t-2)">
                    Current: {operations.report_retention_days} days
                  </span>
                ) : null}
              </div>
              {retentionMessage ? (
                <p className="text-[12.5px] font-medium text-(--good)">{retentionMessage}</p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap items-center justify-between gap-6 border-t border-(--line) pt-6">
          <div className="flex items-center gap-6">
            <div className="flex flex-col">
              <span className={`${MICRO_LABEL} mb-1`}>Configuration</span>
              <Link
                href="/admin/settings/configuration"
                className="flex items-center gap-2 text-[13px] font-semibold text-(--t-2) transition-colors hover:text-(--t-1)"
              >
                <Layout size={14} className="text-(--purple)" /> Advanced Settings{" "}
                <ExternalLink size={12} />
              </Link>
            </div>
            <div className="flex flex-col border-l border-(--line) pl-6">
              <span className={`${MICRO_LABEL} mb-1`}>Data Retention</span>
              <Link
                href="/admin/audit-retention"
                className="flex items-center gap-2 text-[13px] font-semibold text-(--t-2) transition-colors hover:text-(--t-1)"
              >
                <Database size={14} className="text-(--purple)" /> Retention Policy{" "}
                <ExternalLink size={12} />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
