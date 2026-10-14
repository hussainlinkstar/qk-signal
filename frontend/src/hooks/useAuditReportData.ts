"use client";

import { useCallback, useMemo, useState } from "react";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";
import type { AuditHistoryItem } from "@/types/auditWorkspace";
import { tabs } from "@/types/auditWorkspace";
import {
  getSeoTabData,
  getAeoTabData,
  getGeoTabData,
  getTechnicalTabData,
  getAuditScoreGroups,
  getAuditPrimaryScore,
  getAuditOverallScore,
  getDetailedAuditRecommendations,
  filterBrandOnlyRecommendations,
  getAuditScopedRecommendations,
  getAuditEntities,
} from "@/lib/reportAdapters";
import { buildCompletedAuditScheduleParams } from "@/lib/auditRouting";
import { formatDateTime } from "@/lib/dateFormat";

interface UseAuditReportDataInput {
  activeReport: CanonicalAuditReport | null;
  activeAuditMeta: AuditHistoryItem | null | undefined;
}

export function useAuditReportData({ activeReport, activeAuditMeta }: UseAuditReportDataInput) {
  const [copyStatus, setCopyStatus] = useState("");

  // ---- Target resolution ----
  const activeTargetType: "brand" | "website" =
    activeReport?.target?.type === "brand" || activeAuditMeta?.auditTargetType === "brand"
      ? "brand"
      : "website";

  const activeTargetUrl = (
    activeReport?.target?.url ??
    activeAuditMeta?.targetUrl ??
    activeReport?.url ??
    activeAuditMeta?.url ??
    ""
  ).trim();

  const activeTargetName = (
    activeReport?.target?.name ??
    activeAuditMeta?.targetName ??
    activeTargetUrl
  ).trim();

  const activeTargetLabel = activeTargetName || activeTargetUrl || "selected target";
  const isBrandWithoutUrl = activeTargetType === "brand" && !activeTargetUrl;

  // ---- Tab data ----
  const seoTabData = useMemo(
    () => (activeReport ? getSeoTabData(activeReport) : null),
    [activeReport]
  );
  const aeoTabData = useMemo(
    () => (activeReport ? getAeoTabData(activeReport) : null),
    [activeReport]
  );
  const geoTabData = useMemo(
    () => (activeReport ? getGeoTabData(activeReport) : null),
    [activeReport]
  );
  const technicalTabData = useMemo(
    () => (activeReport ? getTechnicalTabData(activeReport) : null),
    [activeReport]
  );

  const performance = technicalTabData?.performance ?? {};
  const network = technicalTabData?.network ?? {};
  const technicalSignals = technicalTabData?.technicalSignals ?? null;

  // ---- Scores ----
  const scoreGroups = useMemo(
    () => (activeReport ? getAuditScoreGroups(activeReport) : []),
    [activeReport]
  );

  const overallScore = useMemo(() => {
    if (activeReport) {
      const backendOverall = getAuditOverallScore(activeReport);
      if (backendOverall !== null) return backendOverall;
    }
    if (!scoreGroups.length) return 0;
    const total = scoreGroups.reduce((acc, item) => acc + item.score, 0);
    return Math.round(total / scoreGroups.length);
  }, [activeReport, scoreGroups]);

  const seoScore = activeReport ? getAuditPrimaryScore(activeReport, "seo") : 0;
  const aeoScore = activeReport ? getAuditPrimaryScore(activeReport, "aeo") : 0;
  const geoScore = activeReport ? getAuditPrimaryScore(activeReport, "geo") : 0;

  // ---- SEO derived ----
  const seoAudits = seoTabData?.seoAudits ?? [];
  const structuredDataDetected = seoTabData?.structuredDataDetected;
  const seoStatus = seoTabData?.seoStatus;
  const lcpValue = seoTabData?.largestContentfulPaint;
  const clsValue = seoTabData?.cumulativeLayoutShift;

  // ---- AEO derived ----
  const aeoScoreEntries = Object.entries(aeoTabData?.scoreDetails ?? {}).filter(
    ([key]) => !["score", "recommendations", "summary"].includes(key)
  );
  const aeoEntityClarity =
    aeoTabData?.entityClarity ?? "Entity clarity signals were not provided in this assessment.";
  const aeoRecommendations = activeReport ? getAuditScopedRecommendations(activeReport, "aeo") : [];
  const aeoReadabilityFindings = Array.isArray(aeoTabData?.aeo?.readability_findings)
    ? aeoTabData.aeo.readability_findings
    : [];
  const aeoRewriteSuggestions = Array.isArray(aeoTabData?.aeo?.rewrite_suggestions)
    ? aeoTabData.aeo.rewrite_suggestions
    : [];

  // ---- GEO derived ----
  const geoSummary = geoTabData?.summary ?? "No generative visibility summary available.";
  const geoRecommendations = activeReport ? getAuditScopedRecommendations(activeReport, "geo") : [];

  // ---- Recommendations ----
  const rawRecommendations = activeReport ? getDetailedAuditRecommendations(activeReport) : [];
  const allRecommendations = isBrandWithoutUrl
    ? filterBrandOnlyRecommendations(rawRecommendations)
    : rawRecommendations;

  // ---- Entities ----
  const normalizedEntities = useMemo(
    () => (activeReport ? getAuditEntities(activeReport) : []),
    [activeReport]
  );

  // ---- Scheduling ----
  const scheduleAuditParams = useMemo(
    () => buildCompletedAuditScheduleParams(activeReport, activeAuditMeta?.auditType),
    [activeAuditMeta?.auditType, activeReport]
  );

  // ---- Tab filtering ----
  const filteredTabs = useMemo(
    () => (isBrandWithoutUrl ? tabs.filter((t) => t.id !== "technical") : [...tabs]),
    [isBrandWithoutUrl]
  );

  // ---- Share / Export ----
  const shareSummary = useMemo(() => {
    if (!activeReport) return "";
    return [
      `Assessment Summary for ${activeTargetLabel}`,
      `Target Type: ${activeTargetType.toUpperCase()}`,
      `Overall Score: ${overallScore}/100`,
      `SEO Score: ${seoScore}/100`,
      `Answer Engine Index: ${aeoScore}/100`,
      `AI Visibility Score: ${geoScore}/100`,
      activeAuditMeta?.createdAt
        ? `Created: ${formatDateTime(activeAuditMeta.createdAt)}`
        : undefined,
    ]
      .filter(Boolean)
      .join("\n");
  }, [
    activeAuditMeta?.createdAt,
    activeReport,
    activeTargetLabel,
    activeTargetType,
    aeoScore,
    geoScore,
    overallScore,
    seoScore,
  ]);

  const handleCopySummary = useCallback(async () => {
    if (!shareSummary) return;
    try {
      await navigator.clipboard.writeText(shareSummary);
      setCopyStatus("Summary copied to clipboard.");
    } catch {
      setCopyStatus("Unable to copy summary. Please copy manually.");
    }
    setTimeout(() => setCopyStatus(""), 2500);
  }, [shareSummary]);

  const handleExportJson = useCallback(() => {
    if (!activeReport || !activeAuditMeta) return;
    const exportPayload = {
      audits: [
        {
          id: activeAuditMeta.id,
          url: activeAuditMeta.url,
          geo_score: activeAuditMeta.geoScore,
          created_at: activeAuditMeta.createdAt,
          full_report: activeReport,
        },
      ],
    };
    const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `audit-export-${activeAuditMeta.id}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }, [activeAuditMeta, activeReport]);

  return {
    // target
    activeTargetType,
    activeTargetUrl,
    activeTargetName,
    activeTargetLabel,
    isBrandWithoutUrl,
    // tab data
    seoTabData,
    aeoTabData,
    geoTabData,
    technicalTabData,
    // convenience fields
    performance,
    network,
    technicalSignals,
    seoAudits,
    structuredDataDetected,
    seoStatus,
    lcpValue,
    clsValue,
    // scores
    overallScore,
    seoScore,
    aeoScore,
    geoScore,
    scoreGroups,
    // aeo derived
    aeoScoreEntries,
    aeoEntityClarity,
    aeoRecommendations,
    aeoReadabilityFindings,
    aeoRewriteSuggestions,
    // geo derived
    geoSummary,
    geoRecommendations,
    // recommendations
    allRecommendations,
    // entities
    normalizedEntities,
    // scheduling
    scheduleAuditParams,
    // tabs
    filteredTabs,
    // export
    shareSummary,
    handleCopySummary,
    handleExportJson,
    copyStatus,
  };
}
