import React from "react";
import { useTranslation } from "react-i18next";
import { Lock } from "lucide-react";

/**
 * signal-MVP `.lockwrap.locked > .lockcontent`: the blurred preview layer
 * behind the lockgate. It renders the approved row anatomy (`.act` for the
 * SEO/AIO detail action plan, `.fix` for the project overview) with generic
 * illustrative copy - never the customer's gated recommendations, which must
 * not reach the DOM for a user without the entitlement. The host keeps the
 * layer `aria-hidden`, blurred and inert; nothing here is interactive.
 */

const ROW_KEYS = ["r1", "r2", "r3"] as const;
// SIGV2-1211: the `.act` rows used to carry an illustrative "+8 PTS" badge.
// That is the worst case of a figure that traces to nothing: it is shown to a
// customer whose plan cannot see the real list, so there is no number behind
// it at all. Both row shapes now state impact as a category, like the live
// rows they stand in for, and `accent` only tints the category chip.
const ROW_IMPACTS = ["high", "high", "medium"] as const;

/** `.act` rows: heading, description, chip meta (category, effort, impact). */
export function LockedActPreview({ accent = "purple" }: { accent?: "purple" | "blue" }) {
  const { t } = useTranslation();
  return (
    <>
      {ROW_KEYS.map((key, i) => (
        <div
          className="flex items-center gap-4 border-t border-t-(--line-2) px-[22px] py-[18px] first:border-t-0"
          key={key}
        >
          {/* The approved `.act` row's leading column, kept empty: it held the
              illustrative points badge, and the row it stands in for keeps the
              same empty column. */}
          <div className="w-16 flex-none text-center" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
              {t(`signalLockedPreview.${key}Title`)}
            </h3>
            <p className="mt-[5px] text-[13px] leading-[1.5] text-(--t-2)">
              {t(`signalLockedPreview.${key}Desc`)}
            </p>
            <div className="mt-[9px] flex flex-wrap items-center gap-2">
              <span
                className={`rounded-[6px] px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] ${
                  accent === "blue"
                    ? "bg-(--line-2) text-(--t-2)"
                    : "bg-(--purple-a10) text-(--purple)"
                }`}
              >
                {t(`signalLockedPreview.${key}Type`)}
              </span>
              <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
                {t(`signalLockedPreview.${key}Effort`)}
              </span>
              <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
                {t("signalFixes.plan.impactRated", {
                  level: t(`signalFixes.plan.level.${ROW_IMPACTS[i]}`),
                })}
              </span>
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

/** `.fix` rows: `.no` counter, heading, description, impact + category chips,
    and the advisor side panel, matching the unlocked overview row shape. */
export function LockedFixPreview() {
  const { t } = useTranslation();
  return (
    <>
      {ROW_KEYS.map((key, i) => (
        <div
          className="grid grid-cols-1 border-t border-t-(--line-2) px-[22px] py-4 first-of-type:border-t-0 lg:grid-cols-[1fr_340px]"
          key={key}
        >
          <div className="flex items-start gap-[18px]">
            <div className="w-[34px] flex-none font-(family-name:--disp) text-[26px] font-normal leading-[1.1] text-(--fix-num)">
              {String(i + 1).padStart(2, "0")}
            </div>
            <div className="min-w-0 flex-1 wrap-anywhere">
              <h3 className="m-0 font-(family-name:--disp) text-[14.5px] font-bold tracking-[-0.01em]">
                {t(`signalLockedPreview.${key}Title`)}
              </h3>
              <p className="mt-[5px] text-[13px] leading-[1.5] text-(--t-2)">
                {t(`signalLockedPreview.${key}Desc`)}
              </p>
              <div className="mt-[9px] flex items-center gap-2 max-md:flex-wrap">
                <span
                  className={`rounded-[6px] px-2 py-[3px] font-mono text-[10.5px] uppercase tracking-[0.04em] ${
                    ROW_IMPACTS[i] === "high"
                      ? "bg-(--bad-s) text-(--bad)"
                      : "bg-(--warn-s) text-(--warn)"
                  }`}
                >
                  {t(
                    ROW_IMPACTS[i] === "high"
                      ? "signalOverview.impactHigh"
                      : "signalOverview.impactMedium"
                  )}
                </span>
                <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] font-mono text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
                  {t(`signalLockedPreview.${key}Type`)}
                </span>
              </div>
            </div>
          </div>
          <div className="relative ml-6 flex flex-col justify-center rounded-[12px] bg-(--panel-soft) px-[18px] py-3.5 max-lg:mt-3">
            <span className="absolute left-[18px] top-4 text-(--purple-deep)">
              <Lock size={18} strokeWidth={2} aria-hidden="true" />
            </span>
            <h4 className="m-0 pl-7 font-(family-name:--disp) text-[13px] font-bold tracking-[-0.01em]">
              {t("signalOverview.advisorPlan")}
            </h4>
            <p className="m-0 mt-1 pl-7 text-[12px] leading-[1.45] text-(--t-2)">
              {t("signalOverview.advisorPlanDesc")}
            </p>
          </div>
        </div>
      ))}
    </>
  );
}
