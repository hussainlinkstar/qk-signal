"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Shield, RefreshCcw, Zap, Activity, Globe, AlertTriangle } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ClientSafeDate } from "@/lib/dateFormat";
import { PLAN_DISPLAY_NAMES, resolvePlanType } from "@/lib/planCapabilities";

type AdminSubscription = {
  id: number;
  user_id: number;
  user_email: string;
  stripe_customer_id: string;
  stripe_subscription_id: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  plan_type: string;
  status: string;
};

type AdminSubscriptionsResponse = {
  subscriptions: AdminSubscription[];
};

const CHIP =
  "inline-flex items-center gap-1.5 rounded-md border px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const CHIP_NEUTRAL = `${CHIP} border-(--line) bg-(--line-2) text-(--t-2)`;
const CHIP_GOOD = `${CHIP} border-transparent text-(--good) bg-(--good-s)`;

const formatPlanLabel = (plan: string | null) => {
  const canonicalPlan = resolvePlanType(plan);
  return canonicalPlan ? PLAN_DISPLAY_NAMES[canonicalPlan] : plan || "Starter";
};

const TOOL_SELECT = "h-8 w-auto rounded-(--r-sm) px-2.5 text-[12.5px]";

export default function AdminSubscriptionsPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [subscriptions, setSubscriptions] = useState<AdminSubscription[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const planFilter = "";
  const [pageSize, setPageSize] = useState(25);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin billing.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadSubscriptions = useCallback(async () => {
    if (!isSignedIn) {
      return;
    }
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/billing/subscriptions", { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load subscriptions.");
      }
      const payload = (await response.json()) as AdminSubscriptionsResponse;
      setSubscriptions(payload.subscriptions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load subscriptions.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadSubscriptions();
  }, [loadSubscriptions]);

  const controlsDisabled = !isAdmin || isGuardLoading || isLoading;

  const filteredSubscriptions = useMemo(() => {
    return subscriptions.filter((subscription) => {
      if (statusFilter && subscription.status !== statusFilter) {
        return false;
      }
      if (planFilter && subscription.plan_type !== planFilter) {
        return false;
      }
      return true;
    });
  }, [planFilter, statusFilter, subscriptions]);

  const columns: SignalDataTableColumn<AdminSubscription>[] = [
    {
      key: "user",
      header: "User",
      sortable: true,
      sortValue: (s) => s.user_email,
      renderCell: (s) => (
        <>
          <div className="font-semibold text-(--t-1)">{s.user_email}</div>
          <div className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--t-3)">
            UID: {s.user_id}
          </div>
        </>
      ),
    },
    {
      key: "plan",
      header: "Subscription plan",
      sortable: true,
      sortValue: (s) => s.plan_type,
      renderCell: (s) => <span className={CHIP_NEUTRAL}>{formatPlanLabel(s.plan_type)}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortValue: (s) => s.status,
      renderCell: (s) => (
        <span className={s.status === "active" ? CHIP_GOOD : CHIP_NEUTRAL}>
          {s.status === "active" ? <Activity size={10} /> : <Shield size={10} />}
          {s.status}
        </span>
      ),
    },
    {
      key: "renewal",
      header: "Renewal date",
      sortable: true,
      sortValue: (s) => s.current_period_end ?? "",
      renderCell: (s) => (
        <span className="text-(--t-2)">
          {s.current_period_end ? <ClientSafeDate date={s.current_period_end} /> : "-"}
        </span>
      ),
    },
    {
      key: "autoRenew",
      header: "Auto-renew",
      sortable: true,
      sortValue: (s) => (s.cancel_at_period_end ? 1 : 0),
      renderCell: (s) => (
        <span
          className={`font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] ${s.cancel_at_period_end ? "text-(--warn)" : "text-(--good)"}`}
        >
          {s.cancel_at_period_end ? "Disabled" : "Operational"}
        </span>
      ),
    },
    {
      key: "billing",
      header: "Billing details",
      renderCell: (s) => (
        <div className="flex flex-col gap-1 font-(family-name:--mono) text-[10.5px] tracking-[0.04em] text-(--t-3)">
          <span className="flex items-center gap-1.5">
            <Globe size={10} /> {s.stripe_customer_id}
          </span>
          <span className="flex items-center gap-1.5">
            <RefreshCcw size={10} /> {s.stripe_subscription_id ?? "-"}
          </span>
        </div>
      ),
    },
  ];

  return (
    <>
      <DashboardPageIntro icon={Zap} title="Platform subscriptions">
        Monitor and manage all active user subscriptions and billing status. Authorized access only.
      </DashboardPageIntro>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <SignalDataTable
        columns={columns}
        rows={filteredSubscriptions}
        rowKey={(s) => s.id}
        pageSize={pageSize}
        searchPlaceholder="Search by user email..."
        searchText={(s) => s.user_email}
        metaLabel={`${filteredSubscriptions.length} / ${subscriptions.length} found`}
        tools={
          <>
            <NativeSelect
              variant="auth"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              disabled={controlsDisabled}
              aria-label="Status filter"
              className={TOOL_SELECT}
            >
              <option value="">Any status</option>
              <option value="active">Active</option>
              <option value="canceled">Canceled</option>
              <option value="past_due">Past Due</option>
              <option value="incomplete">Incomplete</option>
            </NativeSelect>
            <NativeSelect
              variant="auth"
              value={pageSize}
              onChange={(event) => setPageSize(Number(event.target.value))}
              disabled={controlsDisabled}
              aria-label="Records per page"
              className={TOOL_SELECT}
            >
              {[10, 25, 50].map((size) => (
                <option key={size} value={size}>
                  {size} records
                </option>
              ))}
            </NativeSelect>
          </>
        }
        emptyLabel={isLoading ? "Loading subscriptions..." : "No subscriptions found."}
      />
    </>
  );
}
