"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { REPORT_BLOCK } from "./reportBlock";
import ScoreFactorRow, { type ScoreFactor } from "./ScoreFactorRow";

/**
 * "What makes up your SEO score", on the approved anatomy.
 *
 * This panel used to be two shadowed cards floating over the disclosure that
 * contains them, followed by a section headed "Atomic SEO Protocols / Search
 * Visibility Checks" and a badge reading "OS OK". Edward's reaction was
 * "jesus...", and he was right: the words were ours rather than a customer's,
 * the badges were unreadable, the cards broke out of their panel, and a header
 * announced a section that rendered nothing.
 *
 * It is rebuilt on the shape the approved design already defines for exactly
 * this question, `.st` in `signal.css`, used on `Signal SEO Detail.html`: one
 * flat card, one row per factor, each row a score, a title, a one-line
 * description and a bar, expanding to "Why you are here" and "How to improve".
 *
 * Three factors, because three is what the scan actually measures. The
 * individual page checks live inside the On-page row rather than in a section
 * of their own, which is where a reader looks for them and which removes a
 * heading that had nothing under it when the list was empty.
 *
 * Nothing here invents a number. A factor with no measurement says so and is
 * not scored, which is the same rule the rest of the product follows.
 */

type SeoTabProps = {
  performance: Record<string, unknown>;
  seoAudits: { title?: string; score?: number }[];
  structuredDataDetected: boolean | undefined;
  lcpValue: string | undefined;
  clsValue: string | undefined;
  isBrandWithoutUrl?: boolean;
};

// SIGV2-1317: the factor row lives in `ScoreFactorRow` now, so the AIO score
// is explained with the same anatomy as this one. It was local here, which is
// why AEO and GEO ended up with a different shape for the same question.

export default function SeoTab({
  performance,
  seoAudits,
  structuredDataDetected,
  lcpValue,
  clsValue,
  isBrandWithoutUrl,
}: SeoTabProps) {
  const { t } = useTranslation();

  if (isBrandWithoutUrl) {
    return (
      <div className={REPORT_BLOCK}>
        <p className="m-0 max-w-prose text-[13px] leading-[1.55] text-(--t-2)">
          {t("signalSeoFactors.unavailableBody")}
        </p>
      </div>
    );
  }

  const rawPerformance = performance?.["performance_score"];
  const performanceScore = typeof rawPerformance === "number" ? rawPerformance : null;

  const checks = (seoAudits || [])
    .filter((audit) => typeof audit?.score === "number" && audit.title)
    .map((audit) => ({ title: String(audit.title), score: audit.score as number }));
  const passed = checks.filter((check) => check.score >= 0.9).length;

  const technicalEvidence = [
    lcpValue ? t("signalSeoFactors.technicalLcp", { value: lcpValue }) : null,
    clsValue ? t("signalSeoFactors.technicalCls", { value: clsValue }) : null,
  ].filter((line): line is string => Boolean(line));

  const factors: ScoreFactor[] = [
    {
      id: "technical",
      title: t("signalSeoFactors.technical"),
      description: t("signalSeoFactors.technicalDesc"),
      score: performanceScore,
      why:
        performanceScore === null
          ? t("signalSeoFactors.technicalWhyUnmeasured")
          : performanceScore >= 80
            ? t("signalSeoFactors.technicalWhyGood")
            : performanceScore >= 50
              ? t("signalSeoFactors.technicalWhyMixed")
              : t("signalSeoFactors.technicalWhyPoor"),
      evidence: technicalEvidence,
      fixes:
        performanceScore === null || performanceScore >= 80
          ? [t("signalSeoFactors.technicalFixGeneral")]
          : [t("signalSeoFactors.technicalFixLcp"), t("signalSeoFactors.technicalFixCls")],
    },
    {
      id: "schema",
      title: t("signalSeoFactors.schema"),
      description: t("signalSeoFactors.schemaDesc"),
      // A boolean is a real measurement; `undefined` means the check did not run.
      score: structuredDataDetected === undefined ? null : structuredDataDetected ? 100 : 0,
      why: structuredDataDetected
        ? t("signalSeoFactors.schemaWhyPresent")
        : t("signalSeoFactors.schemaWhyMissing"),
      fixes: structuredDataDetected ? undefined : [t("signalSeoFactors.schemaFix")],
    },
    {
      id: "on-page",
      title: t("signalSeoFactors.onPage"),
      description: checks.length
        ? t("signalSeoFactors.onPageDesc", { count: checks.length })
        : t("signalSeoFactors.onPageDescNone"),
      score: checks.length
        ? Math.round(
            (checks.reduce((total, check) => total + check.score, 0) / checks.length) * 100
          )
        : null,
      why: !checks.length
        ? t("signalSeoFactors.onPageWhyNone")
        : passed === checks.length
          ? t("signalSeoFactors.onPageWhyAll")
          : t("signalSeoFactors.onPageWhy", { passed, total: checks.length }),
      // The checks themselves, where a reader looks for them: inside the factor
      // they belong to, rather than under a heading of their own that rendered
      // empty whenever the list was.
      checks: checks.filter((check) => check.score < 0.9),
    },
  ];

  // SIGV2-1317: the section says its own name, once.
  //
  // This opened with an `h3` reading "What makes up your SEO score" directly
  // under the disclosure heading that already says it, then wrapped the rows
  // in a card inside the card the disclosure draws. So the reader met the
  // same sentence twice and three borders deep.
  //
  // The factor rows are the content. They carry their own `.st` rule, so they
  // divide without being boxed.
  return (
    <div className={REPORT_BLOCK}>
      {factors.map((factor) => (
        <ScoreFactorRow key={factor.id} group="seo" factor={factor} />
      ))}
    </div>
  );
}
