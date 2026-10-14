"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { cx } from "@/components/ui/utils";
import { REPORT_BLOCK, REPORT_BLOCK_DIVIDED } from "./reportBlock";

/**
 * "Site health", on the approved visual language (SIGV2-1302).
 *
 * This was three glowing tiles and two shadowed cards, every label in
 * `font-black uppercase tracking-[0.2em]`, every string value forced to
 * capitals by `formatMetric`, and an empty state drawn at 30% opacity behind a
 * 48px icon. None of that appears in any approved mockup: the design language
 * is flat cards on `--line` borders with mono labels and values in the display
 * font.
 *
 * The data and the i18n keys are unchanged. What changes is that it now reads
 * like the rest of Signal, and that a value is printed as it came rather than
 * shouted.
 */

type TechnicalTabProps = {
  performance: Record<string, unknown>;
  network: Record<string, unknown>;
  technicalSignals?: Record<string, unknown> | null;
};

// signal.css `.card`.
// SIGV2-1317: blocks, not cards. The disclosure around Site health already
// draws the one card this section gets, so three bordered panels inside it
// put the reader three borders deep for one set of numbers.
// `.sec h2`
const TITLE_CLASS = "m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold";
// `.sblock .sd`
const SUB_CLASS = "mb-4 text-[12.5px] text-(--t-3)";
// `.nav .lab`: the one mono label treatment in the design.
const LABEL_CLASS = "font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";

const formatMetric = (
  value: unknown,
  t: (key: string) => string,
  fallback = "signalAuditReport.siteHealth.notMeasured"
): string => {
  if (value === null || value === undefined) {
    return t(fallback);
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : t(fallback);
  }
  if (typeof value === "boolean") {
    return value
      ? t("signalAuditReport.siteHealth.supported")
      : t("signalAuditReport.siteHealth.notSupported");
  }
  if (typeof value === "string" && value.trim()) {
    // SIGV2-1302: as it came. This used to return `value.toUpperCase()`, which
    // is how "h2" became "H2" and every protocol string arrived shouting.
    return value.trim();
  }
  return t(fallback);
};

function Metric({
  label,
  value,
  measured = true,
}: {
  label: string;
  value: string;
  measured?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className={LABEL_CLASS}>{label}</div>
      <div
        data-metric-value={measured ? "measured" : "unmeasured"}
        className={cx(
          "mt-1 font-(family-name:--disp) text-[18px] font-bold leading-none tracking-[-0.01em]",
          measured ? "text-(--t-1)" : "text-[13px] font-semibold text-(--t-3)"
        )}
      >
        {value}
      </div>
    </div>
  );
}

export default function TechnicalTab({
  performance,
  network,
  technicalSignals,
}: TechnicalTabProps) {
  const { t } = useTranslation();
  const rawChecks = technicalSignals?.seo_audit_checks;
  const checks = Array.isArray(rawChecks)
    ? rawChecks
        .map((entry) => {
          if (typeof entry === "string") {
            return entry;
          }
          if (entry && typeof entry === "object") {
            const payload = entry as Record<string, unknown>;
            return (
              (typeof payload.title === "string" && payload.title) ||
              (typeof payload.name === "string" && payload.name) ||
              (typeof payload.check === "string" && payload.check) ||
              null
            );
          }
          return null;
        })
        .filter((entry): entry is string => Boolean(entry))
    : [];

  const hasPerformanceData = Object.keys(performance).length > 0;
  const perfScore = performance.performance_score ?? performance.score;
  const perfLcp = performance.largest_contentful_paint ?? performance.lcp_ms;
  const perfCls = performance.cumulative_layout_shift ?? performance.cls;
  const notCollected = t("signalAuditReport.siteHealth.notCollected");

  return (
    <div className={REPORT_BLOCK}>
      <div data-site-health="performance">
        <div className="grid gap-5 sm:grid-cols-3">
          <Metric
            label={t("signalAuditReport.siteHealth.perfScore")}
            value={hasPerformanceData ? formatMetric(perfScore, t) : notCollected}
            measured={hasPerformanceData && perfScore !== null && perfScore !== undefined}
          />
          <Metric
            label={t("signalAuditReport.siteHealth.lcp")}
            value={hasPerformanceData ? formatMetric(perfLcp, t) : notCollected}
            measured={hasPerformanceData && perfLcp !== null && perfLcp !== undefined}
          />
          <Metric
            label={t("signalAuditReport.siteHealth.cls")}
            value={hasPerformanceData ? formatMetric(perfCls, t) : notCollected}
            measured={hasPerformanceData && perfCls !== null && perfCls !== undefined}
          />
        </div>
      </div>

      <div className={cx(REPORT_BLOCK_DIVIDED, "grid gap-x-8 gap-y-5 lg:grid-cols-2")}>
        <div data-site-health="connection">
          <h3 className={TITLE_CLASS}>{t("signalAuditReport.siteHealth.connectTitle")}</h3>
          <p className={SUB_CLASS}>{t("signalAuditReport.siteHealth.connectDesc")}</p>
          <div className="grid gap-5 sm:grid-cols-3">
            <Metric
              label={t("signalAuditReport.siteHealth.protocol")}
              value={formatMetric(network.http_version, t)}
              measured={network.http_version !== null && network.http_version !== undefined}
            />
            <Metric
              label={t("signalAuditReport.siteHealth.http2")}
              value={formatMetric(network.supports_http2, t)}
              measured={network.supports_http2 !== null && network.supports_http2 !== undefined}
            />
            <Metric
              label={t("signalAuditReport.siteHealth.http3")}
              value={
                network.supports_http3_inferred === true
                  ? t("signalAuditReport.siteHealth.http3Likely")
                  : network.supports_http3_inferred === false
                    ? t("signalAuditReport.siteHealth.notDetected")
                    : t("signalAuditReport.siteHealth.notMeasured")
              }
              measured={network.supports_http3_inferred !== undefined}
            />
          </div>
        </div>

        <div data-site-health="checks">
          <h3 className={TITLE_CLASS}>{t("signalAuditReport.siteHealth.checksTitle")}</h3>
          <p className={SUB_CLASS}>{t("signalAuditReport.siteHealth.checksDesc")}</p>
          {checks.length > 0 ? (
            <ul className="m-0 list-none p-0">
              {checks.map((check, index) => (
                <li
                  key={`${check}-${index}`}
                  className="border-t border-(--line-2) py-2 text-[13px] text-(--t-1) first:border-t-0"
                >
                  {check}
                </li>
              ))}
            </ul>
          ) : (
            // SIGV2-1302: the empty state says what it is, in the same type as
            // everything else. It used to be a 48px icon at 30% opacity under
            // a capitalised line, which read as a decoration rather than an
            // answer, and reserved 200px of empty card to do it.
            <p className="m-0 text-[13px] leading-[1.55] text-(--t-3)">
              {t("signalAuditReport.siteHealth.checksEmpty")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
