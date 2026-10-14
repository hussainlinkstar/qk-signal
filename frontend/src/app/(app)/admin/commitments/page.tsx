"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Gauge, RefreshCcw } from "lucide-react";
import Button from "@/components/ui/Button";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { formatDateTime } from "@/lib/dateFormat";

type AdminCommitment = {
  id: number;
  user_id: number;
  user_email: string;
  tier: string;
  committed_credits: number;
  monthly_fee_usd: number;
  rate_per_credit: number;
  status: string;
  cancel_at_period_end: boolean;
  current_cycle_end: string | null;
  credits_used: number;
  overage_credits: number;
  usage_pct: number;
  pending_tier: string | null;
};

type AdminCommitmentsResponse = {
  commitments: AdminCommitment[];
  page: number;
  page_size: number;
  total: number;
};

type AdminCommitmentsOverview = {
  total_commitments: number;
  active_commitments: number;
  pending_cancellations: number;
  commitment_mrr_usd: number;
  average_usage_pct: number;
  total_overage_credits: number;
};

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-[12px] border border-(--line) bg-(--paper) px-[18px] py-4">
      <div
        className={`font-(family-name:--disp) text-[28px] font-extrabold tracking-[-0.02em] ${accent ?? "text-(--t-1)"}`}
      >
        {value}
      </div>
      <div className="mt-0.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
        {label}
      </div>
    </div>
  );
}

export default function AdminCommitmentsPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();
  const [overview, setOverview] = useState<AdminCommitmentsOverview | null>(null);
  const [data, setData] = useState<AdminCommitmentsResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin commitments.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadData = useCallback(async () => {
    if (!isSignedIn) {
      return;
    }
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const [overviewResponse, commitmentsResponse] = await Promise.all([
        fetch("/api/admin/billing/commitments/overview", { headers }),
        fetch("/api/admin/billing/commitments?page=1&page_size=50", { headers }),
      ]);
      if (!overviewResponse.ok) {
        const payload = await overviewResponse.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load commitment overview.");
      }
      if (!commitmentsResponse.ok) {
        const payload = await commitmentsResponse.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load commitments.");
      }
      setOverview((await overviewResponse.json()) as AdminCommitmentsOverview);
      setData((await commitmentsResponse.json()) as AdminCommitmentsResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load commitments.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const controlsDisabled = !isAdmin || isGuardLoading || isLoading;

  const columns: SignalDataTableColumn<AdminCommitment>[] = [
    {
      key: "customer",
      header: "Customer",
      sortable: true,
      sortValue: (item) => item.user_email,
      renderCell: (item) => (
        <>
          <div className="font-semibold text-(--t-1)">{item.user_email}</div>
          <div className="text-[12px] text-(--t-3)">User #{item.user_id}</div>
        </>
      ),
    },
    {
      key: "tier",
      header: "Tier",
      sortable: true,
      sortValue: (item) => item.tier,
      renderCell: (item) => (
        <>
          <div className="font-semibold text-(--t-1)">{item.tier.replace(/_/g, " ")}</div>
          {item.pending_tier ? (
            <div className="mt-1 text-[12px] text-(--purple)">Pending: {item.pending_tier}</div>
          ) : null}
        </>
      ),
    },
    {
      key: "fee",
      header: "Monthly fee",
      sortable: true,
      sortValue: (item) => item.monthly_fee_usd,
      renderCell: (item) => formatCurrency(item.monthly_fee_usd),
    },
    {
      key: "usage",
      header: "Usage",
      sortable: true,
      sortValue: (item) => item.usage_pct,
      renderCell: (item) => (
        <>
          <div className="text-(--t-1)">
            {item.credits_used.toLocaleString()} / {item.committed_credits.toLocaleString()}
          </div>
          <div className="mt-2 h-2 w-40 overflow-hidden rounded-full bg-(--line-2)">
            <div
              className={`h-full rounded-full ${
                item.overage_credits > 0
                  ? "bg-(--bad)"
                  : item.usage_pct >= 80
                    ? "bg-(--warn)"
                    : "bg-(--purple)"
              }`}
              style={{ width: `${Math.min(item.usage_pct, 100)}%` }}
            />
          </div>
          <div className="mt-1 flex items-center gap-2 text-[12px] text-(--t-2)">
            <span>{item.usage_pct}% used</span>
            {item.overage_credits > 0 ? (
              <span className="inline-flex items-center gap-1 text-(--warn)">
                <AlertTriangle className="h-3 w-3" />
                {item.overage_credits} overage
              </span>
            ) : null}
          </div>
        </>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortValue: (item) => item.status,
      renderCell: (item) => (
        <>
          <div className="font-semibold text-(--t-1)">{item.status}</div>
          {item.cancel_at_period_end ? (
            <div className="text-[12px] text-(--warn)">Cancels at period end</div>
          ) : null}
        </>
      ),
    },
    {
      key: "cycleEnd",
      header: "Cycle end",
      sortable: true,
      sortValue: (item) => item.current_cycle_end ?? "",
      renderCell: (item) => (
        <span className="text-(--t-2)">
          {item.current_cycle_end ? formatDateTime(item.current_cycle_end) : "N/A"}
        </span>
      ),
    },
  ];

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void loadData()}
          disabled={controlsDisabled}
          aria-label="Refresh"
          title="Refresh"
          className="h-8 w-8 p-0"
        >
          <RefreshCcw size={14} className={isLoading ? "animate-spin" : ""} />
        </Button>
      ),
    });
    return () => setHeader(null);
  }, [controlsDisabled, isLoading, loadData, setHeader]);

  return (
    <>
      <DashboardPageIntro icon={Gauge} title="Quotas & commitments">
        Monitor monthly credit commitments, cycle usage, pending cancellations, and overage
        exposure.
      </DashboardPageIntro>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <section className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Stat label="Active" value={String(overview?.active_commitments ?? 0)} />
        <Stat label="Total" value={String(overview?.total_commitments ?? 0)} />
        <Stat label="Commitment MRR" value={formatCurrency(overview?.commitment_mrr_usd ?? 0)} />
        <Stat label="Avg usage" value={`${overview?.average_usage_pct ?? 0}%`} />
        <Stat
          label="Overage credits"
          value={String(overview?.total_overage_credits ?? 0)}
          accent="text-(--warn)"
        />
        <Stat label="Pending cancellations" value={String(overview?.pending_cancellations ?? 0)} />
      </section>

      <SignalDataTable
        columns={columns}
        rows={data?.commitments ?? []}
        rowKey={(item) => item.id}
        pageSize={50}
        metaLabel={`${data?.total ?? 0} commitments`}
        emptyLabel={isLoading ? "Loading commitments..." : "No commitments found."}
      />
    </>
  );
}
