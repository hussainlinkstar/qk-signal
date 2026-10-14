import type { MetricTrendPoint } from "@/types/dashboardCharts";
import type { AeoSiteStatsResponse } from "@/services/auditService";

export type AnswerabilityFunnelData = {
  totalAudits: number;
  aiReadablePages: number;
  directAnswerHits: number;
  directAnswerHitsShareTotal: number;
};

export const buildAnswerabilityFunnelData = (
  stats: AeoSiteStatsResponse | null,
  fallbackTotalAudits: number,
  fallbackAiReadablePages: number
): AnswerabilityFunnelData => {
  const totalAudits = stats?.audit_count ?? fallbackTotalAudits;
  const directAnswerHits =
    stats?.answer_dominance.site_primary_count ?? Math.max(0, Math.round(totalAudits * 0.5));
  const directAnswerHitsShareTotal =
    stats?.answer_dominance.site_primary_share_total ??
    (totalAudits > 0 ? (directAnswerHits / totalAudits) * 100 : 0);

  return {
    totalAudits,
    aiReadablePages: stats ? totalAudits : Math.max(0, Math.round(fallbackAiReadablePages)),
    directAnswerHits,
    directAnswerHitsShareTotal,
  };
};

export const mapAeoTrustworthinessTrendToMetricSeries = (
  trend: AeoSiteStatsResponse["trustworthiness_trend"]
): MetricTrendPoint[] =>
  [...trend]
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date))
    .reduce<MetricTrendPoint[]>((series, item) => {
      if (typeof item.score !== "number") {
        return series;
      }

      series.push({
        date: item.date,
        value: item.score,
        secondaryValue: item.audit_count,
        signalCoverage: typeof item.signal_coverage === "number" ? item.signal_coverage : undefined,
      });
      return series;
    }, []);

export const resolveTrustworthinessSignalCoverage = (
  stats: AeoSiteStatsResponse | null
): number | null => {
  if (!stats) {
    return null;
  }

  if (typeof stats.trustworthiness_signal_coverage === "number") {
    return stats.trustworthiness_signal_coverage;
  }

  const signalPoints = stats.trustworthiness_trend
    .map((item) => item.signal_coverage)
    .filter((value): value is number => typeof value === "number");

  if (signalPoints.length === 0) {
    return null;
  }

  return signalPoints.reduce((sum, value) => sum + value, 0) / signalPoints.length;
};

export const mapAuthorityIndexTrendToMetricSeries = (
  trend: AeoSiteStatsResponse["authority_index_trend"]
): MetricTrendPoint[] =>
  [...trend]
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date))
    .map((item) => ({
      date: item.date,
      value: item.value,
      secondaryValue: item.audit_count,
      signalCoverage: item.confidence / 100,
    }));
