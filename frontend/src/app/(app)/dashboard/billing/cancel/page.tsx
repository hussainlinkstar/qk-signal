import React from "react";
import Link from "next/link";
import { XCircle } from "lucide-react";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { buttonClasses } from "@/components/ui/Button";

export default function BillingCancelPage() {
  return (
    <div className="dashboard-page-shell space-y-8">
      <DashboardPageIntro icon={XCircle} title="Billing update canceled" color="var(--warning)">
        The checkout flow was canceled. Your current subscription remains unchanged.
      </DashboardPageIntro>

      <div className="rounded border border-(--line) bg-(--line-2)  shadow-inner p-6">
        <h2 className="text-xl font-bold text-(--t-1)">Need to try again?</h2>
        <p className="text-sm text-(--t-2) mt-2">
          You can return to billing to review plans, upgrade, or manage invoices anytime.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/dashboard/billing"
            className={buttonClasses({ variant: "primary", size: "md" })}
          >
            Return to billing
          </Link>
          <Link
            href="/dashboard/billing/history"
            className={buttonClasses({ variant: "ghost", size: "md" })}
          >
            View invoices
          </Link>
        </div>
      </div>
    </div>
  );
}
