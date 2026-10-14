"use client";

import React from "react";
import DashboardModulePage, {
  type DashboardFeature,
} from "@/components/dashboard/DashboardModulePage";
import { useDashboardAuditHistory } from "@/hooks/useDashboardAuditHistory";

export default function GenericDashboardModule({ feature }: { feature: DashboardFeature }) {
  const auditHistoryState = useDashboardAuditHistory();

  return <DashboardModulePage feature={feature} moduleState={auditHistoryState} />;
}
