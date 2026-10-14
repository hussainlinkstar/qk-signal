"use client";

import React, { useCallback, useMemo } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import Card from "@/components/ui/Card";
import { CARD_SUBSECTION_SURFACE_CLASS, CARD_LABEL_CLASS } from "@/components/ui/cardStyleTokens";
import WelcomeOnboardingCard from "@/components/dashboard/WelcomeOnboardingCard";
import { hasPlanCapability } from "@/lib/planCapabilities";
import type { AuditResult } from "@/types/auditResult";

export type DashboardFeature =
  | "overview"
  | "seo"
  | "geo"
  | "aeo"
  | "entities"
  | "competitors"
  | "reports";

type PlanTier = "plan_standard" | "plan_specialist" | "plan_executive";

export type DashboardModuleDataState = {
  audit: AuditResult | null;
  history: AuditResult[];
  isLoading: boolean;
  error: string;
  hasCompletedAudit: boolean;
};

type DashboardModulePageProps = {
  feature: DashboardFeature;
  title?: string;
  subtitle?: string;
  moduleState: DashboardModuleDataState;
  renderModule?: (context: { audit: AuditResult; history: AuditResult[] }) => React.ReactNode;
};

const featurePlanRequirement: Record<DashboardFeature, PlanTier> = {
  overview: "plan_standard",
  seo: "plan_standard",
  geo: "plan_standard",
  aeo: "plan_specialist",
  entities: "plan_specialist",
  competitors: "plan_specialist",
  reports: "plan_executive",
};

export default function DashboardModulePage({
  feature,
  title,
  subtitle,
  moduleState,
  renderModule,
}: DashboardModulePageProps) {
  const { t } = useTranslation();
  // Module pages are intentionally data-source agnostic.
  // They receive prepared state from hooks/containers and only handle layout + access gating.
  const { audit, history, isLoading, error, hasCompletedAudit } = moduleState;
  const showWelcomeState = !isLoading && !error && !hasCompletedAudit;

  const getFeatureLabel = useCallback(
    (targetFeature: DashboardFeature) => t(`dashboard.features.${targetFeature}`),
    [t]
  );

  const getPlanLabel = useCallback(
    (plan: PlanTier) => {
      const labelMap: Record<PlanTier, string> = {
        plan_standard: t("dashboard.plan.neuralCore"),
        plan_specialist: t("dashboard.plan.synapsePro"),
        plan_executive: t("dashboard.plan.singularityElite"),
      };
      return labelMap[plan];
    },
    [t]
  );

  const accessAllowed = useMemo(() => {
    if (!audit) {
      return false;
    }
    return hasPlanCapability(audit.metadata.plan, featurePlanRequirement[feature]);
  }, [audit, feature]);

  const resolvedTitle = title ?? `${getFeatureLabel(feature)} Dashboard`;
  const resolvedSubtitle =
    subtitle ??
    `Review the latest ${getFeatureLabel(feature)} insights from your completed assessment history.`;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-black text-(--t-1)">{resolvedTitle}</h1>
        <p className="mt-2 text-sm text-(--t-2)">{resolvedSubtitle}</p>
      </div>

      {isLoading ? (
        <Card className="p-6 text-(--t-2)">{t("dashboard.loadingLatestAudit")}</Card>
      ) : null}
      {!isLoading && error ? <Card className="p-6 text-rose-300">{error}</Card> : null}
      {showWelcomeState ? <WelcomeOnboardingCard /> : null}

      {!isLoading && !error && hasCompletedAudit && audit ? (
        <>
          {accessAllowed ? (
            renderModule ? (
              renderModule({ audit, history })
            ) : (
              <Card className="space-y-4 p-6">
                <h2 className="text-lg font-semibold text-(--t-1)">Module overview</h2>
                <p className="text-sm text-(--t-2)">
                  Additional module widgets are not configured yet for {getFeatureLabel(feature)}.
                </p>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className={`${CARD_SUBSECTION_SURFACE_CLASS} shadow-inner`}>
                    <p className={CARD_LABEL_CLASS}>SEO</p>
                    <p className="text-3xl font-black text-(--t-1)">
                      {Math.round(audit.scores.seo)}
                    </p>
                  </div>
                  <div className={`${CARD_SUBSECTION_SURFACE_CLASS} shadow-inner`}>
                    <p className={CARD_LABEL_CLASS}>AI visibility</p>
                    <p className="text-3xl font-black text-(--t-1)">
                      {Math.round(audit.scores.geo)}
                    </p>
                  </div>
                  <div className={`${CARD_SUBSECTION_SURFACE_CLASS} shadow-inner`}>
                    <p className={CARD_LABEL_CLASS}>AI answers</p>
                    <p className="text-3xl font-black text-(--t-1)">
                      {Math.round(audit.scores.aeo)}
                    </p>
                  </div>
                </div>
              </Card>
            )
          ) : (
            <Card className="p-6">
              <h2 className="text-lg font-semibold text-(--t-1)">
                {t("dashboard.restricted.title")}
              </h2>
              <p className="mt-2 text-sm text-(--t-2)">
                {t("dashboard.restricted.description", {
                  feature: getFeatureLabel(feature),
                  plan: getPlanLabel(featurePlanRequirement[feature]),
                })}
              </p>
              <Link
                href="/dashboard/billing"
                className="mt-4 inline-flex text-sm font-semibold text-primary hover:underline"
              >
                {t("dashboard.restricted.upgradePlan")}
              </Link>
            </Card>
          )}
        </>
      ) : null}
    </div>
  );
}
