"use client";

import React from "react";
import { Tag } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSignalBarEntrance } from "@/hooks/useSignalChartMotion";
import { isMeasuredSearchType, isPendingSearchType, type SearchType } from "@/lib/reportAdapters";
import { cx } from "@/components/ui/utils";

// signal-MVP `.feeds .ft` icons and accent pairs, keyed by search-type id.
// Palette values only; the layout is the approved feed column.
const TYPE_STYLE: Record<string, { icon: React.ReactNode; bg: string; fg: string }> = {
  brand: {
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <path d="M20.6 13.4L13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z" />
        <circle cx="7.5" cy="7.5" r="1.5" />
      </svg>
    ),
    bg: "#ECFDF5",
    fg: "#059669",
  },
  category: {
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
    bg: "#FFFBEB",
    fg: "#D97706",
  },
  problem: {
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
        <circle cx="12" cy="17" r=".5" />
      </svg>
    ),
    bg: "#FFF1F2",
    fg: "#E11D48",
  },
  feature: {
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <path d="M3.3 7L12 12l8.7-5M12 22V12" />
      </svg>
    ),
    bg: "#F5F3FF",
    fg: "#7C3AED",
  },
  comparison: {
    icon: (
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <path d="M7 16l-4 4 4 4M3 20h13M17 8l4-4-4-4M21 4H8" />
      </svg>
    ),
    bg: "#EFF6FF",
    fg: "#2563EB",
  },
};

const FEED_LABEL_KEY: Record<string, string> = {
  brand: "signalOverview.feedLabelBrand",
  category: "signalOverview.feedLabelCategory",
  problem: "signalOverview.feedLabelProblem",
  comparison: "signalOverview.feedLabelComparison",
  feature: "signalOverview.feedLabelFeature",
};

const FEED_ORDER = Object.keys(FEED_LABEL_KEY);

const FALLBACK_STYLE = {
  icon: <Tag size={16} strokeWidth={2} aria-hidden="true" />,
  bg: "#F3F4F6",
  fg: "#6B7280",
};

/**
 * "Why AI recommends / ignores your website" - the approved `.feeds` row of
 * five `.ft` columns mapped from `getSearchTypes` (the same adapter the AIO
 * drilldown uses, so no second mapper). Every card links to the AIO drilldown,
 * as the mock does.
 *
 * Only a score this project's own AI-engine runs produced is shown
 * (SIGV2-1105). These cards used to render a heuristic estimate labelled
 * "Estimated" whenever no run had measured the type: `scores.seo` under Feature
 * Recognition, `scores.aeo` under Category Visibility, and so on. Those are
 * different quantities rather than approximations, and with no `entity_analysis`
 * or `geo_signals` in the report the five collapsed onto three numbers, which
 * is why the row read as repeated. A card with no measurement says so.
 *
 * The approved `.ft-ratio` line ("7 of 10 answers") is the answers the backend
 * checked for this type and how many showed the brand
 * (`search_types[].answer_ratio`). It had no source at all until SIGV2-1105 and
 * said so on every card, permanently; it keeps saying so for a type with no
 * completed check, because `0 of 0` is not a ratio.
 */
export default function SearchTypeFeeds({ searchTypes }: { searchTypes: SearchType[] }) {
  const { t } = useTranslation();
  const barsRef = useSignalBarEntrance(
    searchTypes.map(({ id, score }) => `${id}:${score}`).join("|")
  );
  const orderedTypes = [...searchTypes].sort(
    (a, b) =>
      (FEED_ORDER.includes(a.id) ? FEED_ORDER.indexOf(a.id) : FEED_ORDER.length) -
      (FEED_ORDER.includes(b.id) ? FEED_ORDER.indexOf(b.id) : FEED_ORDER.length)
  );
  if (searchTypes.length === 0) {
    return null;
  }

  return (
    <section aria-label={t("signalOverview.feedsTitle")} className="leading-[normal]">
      <div className="mb-3.5 flex flex-wrap items-center gap-3">
        <h2 className="m-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em]">
          {t("signalOverview.feedsTitle")}
        </h2>
        <span className="h-4 w-px flex-none bg-(--line-2)" aria-hidden="true" />
        <span className="text-[12.5px] text-(--t-3)">{t("signalOverview.feedsSub")}</span>
      </div>
      <div ref={barsRef} className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {orderedTypes.map((st) => {
          const style = TYPE_STYLE[st.id] ?? FALLBACK_STYLE;
          const labelKey = FEED_LABEL_KEY[st.id];
          const label = labelKey ? t(labelKey) : st.label;
          const measured = isMeasuredSearchType(st);
          // SIGV2-1182: a queued measurement is a third state. "No prompt
          // data yet" on a card whose run is already on the queue is the
          // complaint, so the chip says which of the two it is.
          const pending = !measured && isPendingSearchType(st);
          const trend = typeof st.trend === "number" && st.trend !== 0 ? st.trend : null;
          const ratio = st.answerRatio;
          return (
            <div
              key={st.id}
              className="flex min-w-0 flex-col rounded-[22px] border-0 bg-white px-4 py-4"
              data-search-type={st.id}
              data-measurement-state={measured ? "measured" : pending ? "pending" : "unmeasured"}
            >
              <div className="flex items-center gap-2.5">
                <span
                  className="flex h-9 w-9 flex-none items-center justify-center rounded-[12px]"
                  style={{ background: style.bg, color: style.fg }}
                >
                  {style.icon}
                </span>
                <span className="min-w-0 whitespace-pre-line font-(family-name:--disp) text-[13px] font-bold leading-[1.25] text-[#111827]">
                  {label.replace(" ", "\n")}
                </span>
              </div>
              <span
                className={cx(
                  "mt-3 inline-flex items-center self-start gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-semibold",
                  measured
                    ? "bg-[#ECFDF5] text-[#059669]"
                    : pending
                      ? "bg-[#FFFBEB] text-[#D97706]"
                      : "bg-[#EEF1F6] text-(--t-2)"
                )}
              >
                <span className="h-[5px] w-[5px] rounded-full bg-current" aria-hidden="true" />
                {measured
                  ? t("signalOverview.measured")
                  : pending
                    ? t("signalOverview.feedMeasuringChip")
                    : t("signalOverview.feedNotMeasuredChip")}
              </span>
              <div className="mb-0.5 mt-3 font-(family-name:--disp) text-[32px] font-extrabold leading-none tracking-[-0.03em] text-[#111827]">
                {/* SIGV2-1097: a bare dash reads as a broken figure, so the
                    slot names the state instead. */}
                {measured ? (
                  Math.round(st.score as number)
                ) : (
                  <span className="font-(family-name:--body-font) text-[13px] font-semibold tracking-normal text-(--t-3)">
                    {t("signalOverview.notMeasured")}
                  </span>
                )}
                {measured && (
                  <sub className="align-baseline text-[13px] font-semibold tracking-normal text-(--t-3)">
                    /100
                  </sub>
                )}
                {trend !== null ? (
                  <span
                    className={cx(
                      "ms-1.5 text-[12px] font-semibold",
                      trend > 0 ? "text-[#059669]" : "text-[#E11D48]"
                    )}
                  >
                    {Math.abs(Math.round(trend))}
                    {trend > 0 ? "↗" : "↘"}
                  </span>
                ) : null}
              </div>
              {st.insight ? (
                <p className="m-0 mt-2 flex-1 text-[12px] leading-[1.45] text-(--t-2)">{st.insight}</p>
              ) : null}
              <div className="mb-2 mt-auto pt-3 h-1.5 overflow-hidden rounded-full bg-[#EEF1F6]">
                <i
                  data-signal-bar
                  className="block h-full rounded-full"
                  style={{
                    width: measured ? `${Math.round(st.score as number)}%` : 0,
                    background: style.fg,
                  }}
                />
              </div>
              {/* One line, fixed box. The approved `.ft-ratio` is a single
                  mono line, and this slot now carries two very different
                  strings per locale: pinning the height keeps the card, and
                  so the page, the same height whichever it renders, instead
                  of letting an Arabic font-fallback metric decide it. */}
              <div
                data-answer-ratio={ratio ? "measured" : "unmeasured"}
                className="h-[14px] overflow-hidden whitespace-nowrap text-[11px] font-medium leading-[14px] text-(--t-3)"
              >
                {ratio
                  ? t("signalOverview.answerRatioMeasured", {
                      present: ratio.present,
                      measured: ratio.measured,
                    })
                  : t("signalOverview.answerRatioUnavailable")}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
