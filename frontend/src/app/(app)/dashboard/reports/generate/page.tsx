import React from "react";

import ReportsPageClient, { type ReportFlow } from "./ReportsPageClient";

const REPORT_FLOWS: ReportFlow[] = [
  "standard",
  "aio",
  "seo",
  "executive",
  "project",
  "competitors",
  "financial",
];

const resolveInitialKind = (raw: string | string[] | undefined): ReportFlow | undefined => {
  const candidate = (Array.isArray(raw) ? raw[0] : raw)?.trim().toLowerCase();
  // An unrecognised kind falls through to the wizard's own default rather than
  // being coerced into a different one: a silent wrong-kind fallback is the
  // failure SIGV2-1041 named explicitly.
  return REPORT_FLOWS.find((flow) => flow === candidate);
};

export default async function GenerateReportPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = await searchParams;
  return <ReportsPageClient initialKind={resolveInitialKind(resolvedSearchParams.kind)} />;
}
