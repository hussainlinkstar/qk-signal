"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import {
  Activity,
  Gauge as GaugeIcon,
  Info,
  MessageCircle,
  MousePointerClick,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { UseSiteTrafficResult } from "@/hooks/useSiteTraffic";
import SignalXSell, { type SignalXSellRow } from "@/components/signal/SignalXSell";
import {
  TooltipContent,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
} from "@/components/ui/Tooltip";
import { useSignalEntrance } from "@/hooks/useSignalChartMotion";
import {
  type SiteTrafficBreakdownRow,
  type SiteTrafficChange,
  type SiteTrafficPayload,
} from "@/types/siteTraffic";
import { cx } from "@/components/ui/utils";

// signal-MVP `.kpis .kpi` accent tokens per metric. Palette values only; the
// layout is the approved card (icon chip, mono label, disp value, delta pill,
// 58x28 spark).
const METRIC_ACCENTS: Record<string, { ac: string; bg: string }> = {
  sessions: { ac: "#2563EB", bg: "rgba(37,99,235,.09)" },
  users: { ac: "#D9930B", bg: "rgba(217,147,11,.10)" },
  engagement: { ac: "#E5484D", bg: "rgba(229,72,77,.09)" },
  conversions: { ac: "#9333EA", bg: "rgba(147,51,234,.09)" },
  audience: { ac: "#2563EB", bg: "rgba(37,99,235,.09)" },
};

// signal-MVP `.chan-legend` dot palette, extended with Other (the seventh
// contract bucket the mockup never drew).
const CHANNEL_COLORS: Record<string, string> = {
  organic: "#4ADE80",
  direct: "#3B82F6",
  referral: "#CBD5E1",
  ai: "#A855F7",
  paid: "#F59E0B",
  social: "#EF4444",
  other: "#8A92A1",
};

const ENTRY_MS = 450;
const GRID_MS = 200;
const STAG_MS = 50;

const compact = (v: number | null | undefined) =>
  v === null || v === undefined
    ? null
    : Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v);

const percent = (v: number | null | undefined) =>
  v === null || v === undefined ? null : `${Math.round(v * 100)}%`;

// Contract 3.1: relative changes render as %, share changes as pp. The kind
// on the value decides, never the metric name.
function DeltaPill({ change, plain }: { change: SiteTrafficChange; plain?: boolean }) {
  const { t } = useTranslation();
  if (change.value === null) {
    return null;
  }
  const up = change.value >= 0;
  const text =
    change.kind === "percentage_points"
      ? `${up ? "+" : ""}${change.value.toFixed(1)} ${t("siteTraffic.pp")}`
      : `${up ? "+" : ""}${(change.value * 100).toFixed(2)}%`;
  // `.delta` in the approved KPI card is plain mono text, colour only - no
  // background pill. `.cl-delta` in the donut legend is the faint tinted pill.
  if (plain) {
    return (
      <span
        className={cx(
          "whitespace-nowrap font-mono text-[11.5px] font-medium",
          up ? "text-(--good)" : "text-(--bad)"
        )}
        title={t("siteTraffic.vsPrevious")}
      >
        {text} {up ? "↗" : "↘"}
      </span>
    );
  }
  return (
    <span
      className={cx(
        "inline-flex items-center gap-0.5 rounded-full px-[9px] py-[3px] font-mono text-[11.5px] font-semibold",
        up ? "bg-(--good-s) text-(--good)" : "bg-(--bad-s) text-(--bad)"
      )}
      title={t("siteTraffic.vsPrevious")}
    >
      {text} {up ? "↗" : "↘"}
    </span>
  );
}

// signal-MVP `.kpi svg.spark`: 58x28 polyline of the bucketed series.
function Spark({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) {
    return <svg className="h-7 w-[58px]" aria-hidden="true" />;
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const step = 56 / (values.length - 1);
  const points = values
    .map((v, i) => `${(1 + i * step).toFixed(1)},${(26 - ((v - min) / range) * 22).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="h-7 w-[58px]" viewBox="0 0 58 28" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        data-signal-enter="path"
      />
    </svg>
  );
}

function KpiCard({
  metric,
  label,
  value,
  change,
  spark,
  icon,
  unavailable,
  reason,
  xsell,
}: {
  metric: keyof typeof METRIC_ACCENTS;
  label: string;
  value: string | null;
  change?: SiteTrafficChange;
  spark?: number[];
  icon: React.ReactNode;
  unavailable?: string;
  reason?: string;
  // SIGV2-1204: required, not optional. The approved design gives every one
  // of the five cards a help panel, so a card that cannot name its panel
  // content is a card that should not render. Leaving this optional is how
  // the panels went missing on the unmeasured states in the first place.
  xsell: {
    question: string;
    body: string;
    rows: SignalXSellRow[];
  };
}) {
  const { t } = useTranslation();
  const { ac, bg } = METRIC_ACCENTS[metric];
  const card = (
    <div
      className="relative flex h-full items-center gap-[13px] rounded-[14px] border border-(--line) bg-(--panel) px-[18px] py-4"
      data-metric={metric}
      data-xsell=""
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-[14%] -start-px w-1 rounded"
        style={{ backgroundColor: ac }}
      />
      <span
        className="flex h-10 w-10 flex-none items-center justify-center rounded-full"
        style={{ color: ac, backgroundColor: bg }}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        {/* Deliberately `whitespace-nowrap` and not `truncate`, despite the
            label colliding with the delta on the Conversions card (the
            baselines show "CONVERSI0S61%"). Truncating clips to the flex
            width, which also shortened SESSIONS to "SESSI..." on a card
            where the label fit perfectly well: two cards made worse to fix
            one. The collision needs a real answer, a shorter label or a
            layout that stacks them, and that is SIGV2-1282 rather than a
            blunt clip here. */}
        <span className="block whitespace-nowrap font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
          {label}
        </span>
        {unavailable !== undefined ? (
          <>
            <span className="mt-[5px] block whitespace-nowrap text-[12px] font-semibold leading-[1.3] text-(--t-2)">
              {unavailable}
            </span>
            {/* SIGV2-1281: the reason sits under the words it explains.
                It used to render in the right-hand delta and spark column,
                so on a card with neither it floated alone against the far
                edge, as far from "Not measured" as the card allows. It is
                also a statement now, not the question "Why no data?": that
                phrasing invited a click on a span with no handler, no link
                and no tooltip, and the click did nothing. */}
            {reason ? (
              <span className="mt-[3px] flex items-start gap-1 text-[10.5px] leading-[1.35] text-(--t-3)">
                <Info size={11} strokeWidth={2} aria-hidden="true" className="mt-[2px] flex-none" />
                <span className="min-w-0">{reason}</span>
              </span>
            ) : null}
          </>
        ) : (
          <span
            className="mt-[5px] block font-(family-name:--disp) text-[27px] font-black leading-none tracking-[-0.02em]"
            data-signal-enter="count"
            data-signal-count={value ?? undefined}
          >
            {value ?? (
              <span className="font-(family-name:--body-font) text-[12px] font-semibold tracking-normal text-(--t-3)">
                {t("siteTraffic.notMeasured")}
              </span>
            )}
          </span>
        )}
      </div>
      {/* signal-MVP `.kr`: in-flow flex column, delta above spark. The delta
          is plain tinted text with no pill background, so it can never
          occlude an overflowing label the way a painted bubble did. */}
      {change || spark ? (
        <div className="flex flex-none flex-col items-end gap-[5px]">
          {change ? <DeltaPill change={change} plain /> : null}
          {spark ? <Spark values={spark} color={ac} /> : null}
        </div>
      ) : null}
    </div>
  );
  // The approved `.xsell-overlay` panel, on every card without exception.
  return (
    <SignalXSell head={label} question={xsell.question} body={xsell.body} rows={xsell.rows}>
      {card}
    </SignalXSell>
  );
}

// signal-MVP `.chan-donut`: r42 / stroke 15 on a 200x200 svg, legend rows with
// mono delta pills. Shares come from the payload verbatim - never normalised
// and never invented for a bucket the payload omits (null share => no arc).
function ChannelDonut({ payload }: { payload: SiteTrafficPayload }) {
  const { t } = useTranslation();
  const C = 2 * Math.PI * 42;
  let offset = 0;
  const arcs = payload.channel_mix
    .filter((b) => b.share !== null && b.share > 0)
    .map((b) => {
      const len = (b.share! / 100) * C;
      const arc = {
        bucket: b.bucket,
        dash: `${Math.max(len - 1.5, 0)} ${C - Math.max(len - 1.5, 0)}`,
        offset: -offset,
        color: CHANNEL_COLORS[b.bucket] ?? CHANNEL_COLORS.other,
      };
      offset += len;
      return arc;
    });
  const totalSessions = payload.overview.sessions;

  return (
    <div className="flex flex-1 items-center gap-[30px]">
      <div className="relative h-[200px] w-[200px] flex-none">
        <svg viewBox="0 0 110 110" className="h-[200px] w-[200px] -rotate-90" aria-hidden="true">
          <circle cx="55" cy="55" r="42" fill="none" stroke="var(--line)" strokeWidth="15" />
          {arcs.map((arc) => (
            <circle
              key={arc.bucket}
              cx="55"
              cy="55"
              r="42"
              fill="none"
              stroke={arc.color}
              strokeWidth="15"
              strokeDasharray={arc.dash}
              strokeDashoffset={arc.offset}
              data-signal-enter="donut"
            />
          ))}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <b
            className="font-(family-name:--disp) text-[34px] font-black leading-none tracking-[-0.02em]"
            data-signal-enter="count"
            data-signal-delay={ENTRY_MS}
            data-signal-count={compact(totalSessions) ?? undefined}
          >
            {compact(totalSessions) ?? (
              <span className="font-(family-name:--body-font) text-[12px] font-semibold tracking-normal text-(--t-3)">
                {t("siteTraffic.notMeasured")}
              </span>
            )}
          </b>
          <small className="mt-1.5 text-[13.5px] text-(--t-2)">
            {t("siteTraffic.sessionsLabel")}
          </small>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-5">
        {payload.channel_mix.map((bucket, index) => (
          <div
            key={bucket.bucket}
            className="flex items-center gap-2.5 whitespace-nowrap text-[15px] text-(--t-1)"
            data-signal-enter="fade"
            data-signal-delay={ENTRY_MS + index * STAG_MS}
          >
            <span
              className="h-[11px] w-[11px] flex-none rounded-full"
              style={{ backgroundColor: CHANNEL_COLORS[bucket.bucket] ?? CHANNEL_COLORS.other }}
            />
            {bucket.label}
            <span
              className="ms-auto min-w-9 text-end font-(family-name:--disp) font-bold"
              title={bucket.share === null ? t("siteTraffic.shareNotReported") : undefined}
            >
              {bucket.share === null ? (
                <span className="font-(family-name:--body-font) text-[11.5px] font-medium text-(--t-3)">
                  {t("siteTraffic.notReported")}
                </span>
              ) : (
                `${bucket.share}%`
              )}
            </span>
            <DeltaPill change={bucket.share_change} />
          </div>
        ))}
      </div>
    </div>
  );
}

// signal-MVP `.tchart` (app.js stacked()): despite the function name the
// approved chart is NOT stacked - each series maps its own raw value to the
// shared axis, overlaps the others, and fills down to the baseline at 0.07
// opacity with a 2px round-cap smooth stroke. Deliberate deviation kept from
// the original implementation: the mock hardcodes maxV = 60 with "k" ticks;
// we keep the data-derived scale because a fixed axis is mockup placeholder.
// The mock's AI/Organic/Direct/Others channels are not in the contract, which
// provides sessions, pageviews and key events per bucket (recorded deviation).
function TrafficChart({ payload }: { payload: SiteTrafficPayload }) {
  const { t } = useTranslation();
  const W = 900;
  const H = 240;
  const AXIS = 34; // left room for the Y scale
  const FLOOR = 16; // bottom room for x labels
  const series = [
    { key: "sessions" as const, color: "#2563EB", label: t("siteTraffic.metricSessions") },
    { key: "pageviews" as const, color: "#0E7C6B", label: t("siteTraffic.metricPageviews") },
    { key: "key_events" as const, color: "#9333EA", label: t("siteTraffic.metricConversions") },
  ];
  const n = payload.series.length;
  const seriesMax = Math.max(1, ...payload.series.flatMap((p) => series.map((s) => p[s.key])));
  // Data-derived Y scale: round the per-series max up to a clean step for 4 ticks.
  const rawStep = seriesMax / 3;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const step = Math.ceil(rawStep / mag) * mag;
  const yMax = step * 3;
  const xFor = (i: number) => AXIS + (n <= 1 ? 0 : (i * (W - AXIS - 6)) / (n - 1));
  const yFor = (v: number) => H - FLOOR - (v / yMax) * (H - FLOOR - 6);
  // app.js smoothPath(): Catmull-Rom control points converted to cubic beziers.
  const smoothPath = (pts: [number, number][]) => {
    let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[Math.min(pts.length - 1, i + 2)];
      const c1x = p1[0] + (p2[0] - p0[0]) / 6;
      const c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6;
      const c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
    }
    return d;
  };
  const xTicks =
    n <= 8
      ? payload.series.map((p, i) => ({ label: p.bucket, x: xFor(i) }))
      : [0, 1, 2, 3, 4, 5, 6].map((k) => {
          const i = Math.round((k * (n - 1)) / 6);
          return { label: payload.series[i].bucket, x: xFor(i) };
        });

  return (
    <div className="rounded-(--r) border border-(--line) bg-(--panel) px-[22px] pb-2.5 pt-[18px]">
      <div className="mb-1.5 flex flex-wrap items-center gap-4">
        <h2 className="m-0 font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em]">
          {t("siteTraffic.overTime")}
        </h2>
        <div className="ms-auto flex items-center gap-4">
          {series.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-[11.5px] text-(--t-2)">
              <i
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: s.color }}
              />
              {s.label}
            </span>
          ))}
        </div>
      </div>
      {n === 0 ? (
        <div className="flex h-[240px] items-center justify-center text-[13px] text-(--t-3)">
          {t("siteTraffic.noSeries")}
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-[268px] w-full"
          preserveAspectRatio="none"
          role="img"
          aria-label={t("siteTraffic.overTime")}
        >
          {[0, 1, 2, 3].map((k) => {
            const v = step * k;
            const y = yFor(v);
            return (
              <g key={k} data-signal-enter="fade" data-signal-delay={k * STAG_MS}>
                <line x1={AXIS} x2={W - 6} y1={y} y2={y} stroke="var(--line-2)" strokeWidth="1" />
                <text
                  x={AXIS - 6}
                  y={y + 3}
                  textAnchor="end"
                  fontSize="9.5"
                  fill="var(--t-3)"
                  fontFamily="var(--mono)"
                >
                  {v >= 1000 ? `${Math.round(v / 100) / 10}k` : v}
                </text>
              </g>
            );
          })}
          {/* overlaid series: each plotted on its raw value, own baseline fill */}
          {series.map((s, i) => {
            const pts = payload.series.map((p, i) => [xFor(i), yFor(p[s.key])] as [number, number]);
            const line = smoothPath(pts);
            const area = `${line} L${xFor(n - 1).toFixed(1)},${yFor(0).toFixed(1)} L${xFor(0).toFixed(1)},${yFor(0).toFixed(1)} Z`;
            return (
              <g key={s.key}>
                <path
                  d={area}
                  fill={s.color}
                  opacity={0.07}
                  data-signal-enter="fade"
                  data-signal-delay={GRID_MS + i * STAG_MS + ENTRY_MS - 150}
                />
                <path
                  d={line}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                  data-signal-enter="path"
                  data-signal-delay={GRID_MS + i * STAG_MS}
                />
              </g>
            );
          })}
          {/* per-bucket hover targets with the real values as tooltips */}
          {payload.series.map((p, i) => (
            <rect
              key={`hit-${i}`}
              x={n <= 1 ? AXIS : xFor(i) - (W - AXIS - 6) / (2 * (n - 1))}
              y={6}
              width={n <= 1 ? W - AXIS - 6 : (W - AXIS - 6) / (n - 1)}
              height={H - FLOOR - 6}
              fill="transparent"
            >
              <title>
                {`${p.bucket} - ${series.map((s) => `${s.label}: ${p[s.key]}`).join(", ")}`}
              </title>
            </rect>
          ))}
          {xTicks.map((tick, i) => (
            <text
              key={`x-${i}`}
              x={tick.x}
              y={H - 2}
              textAnchor="middle"
              fontSize="9.5"
              fill="var(--t-3)"
            >
              {tick.label}
            </text>
          ))}
        </svg>
      )}
    </div>
  );
}

function StateCard({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-(--line) bg-(--panel) px-6 py-[22px] text-center">
      <h3 className="m-0 font-(family-name:--disp) text-[16px] font-bold">{title}</h3>
      <p className="m-0 max-w-[520px] text-[13px] leading-[1.5] text-(--t-2)">{body}</p>
      {action}
    </div>
  );
}

function ConnectAction({ label, href }: { label: string; href: string }) {
  return (
    <Link
      href={href}
      className="inline-flex h-[38px] items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] text-[13.5px] font-semibold leading-[normal] text-(--panel) hover:brightness-95 max-md:min-h-11"
    >
      {label}
    </Link>
  );
}

export default function SiteTrafficSection({
  state,
  projectId,
}: {
  state: UseSiteTrafficResult;
  projectId: string;
}) {
  const { t } = useTranslation();
  const { traffic, loading, error, refetch } = state;
  const entranceRef = useSignalEntrance<HTMLElement>(
    `traffic:${traffic && traffic.status === "ok" ? traffic.series.length : "idle"}`
  );

  const payload = useMemo(
    () => (traffic && traffic.status === "ok" ? (traffic as SiteTrafficPayload) : null),
    [traffic]
  );

  const qualityFlags = useMemo(() => {
    if (!payload) return [] as string[];
    const flags: string[] = [];
    if (payload.data_quality?.data_loss_from_other_row) flags.push(t("siteTraffic.flagOtherRow"));
    if (payload.data_quality?.subject_to_thresholding)
      flags.push(t("siteTraffic.flagThresholding"));
    if (payload.data_quality?.truncated) flags.push(t("siteTraffic.flagTruncated"));
    return flags;
  }, [payload, t]);

  /* Contract 3/7: the measured window, the comparison window, the property
     timezone and the freshness come from the payload, never from a
     client-side range calculation. The contract requires them to be stated,
     not to occupy their own paragraph: they used to render as a line under
     the charts, 26px of vertical flow the approved design has no element for,
     which pushed every section below the traffic block out of alignment
     (SIGV2-1125). They now hang off this block's own GA4 provenance badge,
     which covers the KPI row as well as the charts and costs no height.
     Keyboard reachable: the badge is a real button, so the facts are not
     hover-only. */
  const provenance = payload
    ? t("siteTraffic.rangeLine", {
        start: payload.start_date,
        end: payload.end_date,
        prevStart: payload.comparison_start_date,
        prevEnd: payload.comparison_end_date,
        tz: payload.property_timezone,
        freshness: payload.data_freshness,
      })
    : null;

  const GA4_BADGE_CLASS =
    "rounded-[5px] border border-(--line) px-[7px] py-0.5 font-mono text-[10px] text-(--t-3)";

  const secHeader = (
    <div className="mb-3 flex flex-wrap items-center gap-3">
      <h2 className="m-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em]">
        {t("siteTraffic.title")}
      </h2>
      <span className="h-4 w-px flex-none bg-(--line-2)" aria-hidden="true" />
      <span className="flex items-center gap-1 text-[12.5px] text-(--t-3)">
        <span className="inline-block h-[13px] w-[13px] rounded-[3px] bg-[conic-gradient(#F9AB00_0_25%,#E37400_0_50%,#34A853_0_75%,#4285F4_0)]" />
        {t("siteTraffic.gaSource")}
      </span>
      {provenance ? (
        <TooltipProvider delayDuration={0}>
          <TooltipRoot>
            <TooltipTrigger asChild>
              <button
                type="button"
                data-traffic-provenance
                aria-label={t("siteTraffic.provenanceLabel")}
                className={cx(
                  GA4_BADGE_CLASS,
                  "cursor-help focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
                )}
              >
                GA4
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-80 font-mono leading-[1.5]">
              {provenance}
            </TooltipContent>
          </TooltipRoot>
        </TooltipProvider>
      ) : (
        <span className={GA4_BADGE_CLASS}>GA4</span>
      )}
    </div>
  );

  if (loading && !traffic) {
    return (
      <section aria-label={t("siteTraffic.title")}>
        {secHeader}
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-[76px] animate-pulse rounded-[14px] border border-(--line) bg-(--panel)"
            />
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section aria-label={t("siteTraffic.title")}>
        {secHeader}
        <StateCard
          title={t("siteTraffic.loadErrorTitle")}
          body={error}
          action={
            <button
              type="button"
              onClick={() => void refetch()}
              className="inline-flex h-[38px] items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold hover:border-(--line-btn-hover)"
            >
              {t("common.tryAgain")}
            </button>
          }
        />
      </section>
    );
  }

  if (traffic && traffic.status === "disconnected") {
    // The next step depends on the binding and workspace connection state.
    // Bound but switched off -> say so and send them back to Connected data;
    // account connected -> the missing piece is the per-project property
    // binding, made there too; account missing -> connect it on the workspace
    // connections page first.
    if (state.ga4BoundInactive === true) {
      return (
        <section aria-label={t("siteTraffic.title")}>
          {secHeader}
          <StateCard
            title={t("siteTraffic.inactiveTitle")}
            body={t("siteTraffic.inactiveBody")}
            action={
              <ConnectAction
                label={t("siteTraffic.reactivateCta")}
                href={`/dashboard/projects/${projectId}/settings#data-sources`}
              />
            }
          />
        </section>
      );
    }
    const accountConnected = state.ga4WorkspaceConnected === true;
    return (
      <section aria-label={t("siteTraffic.title")}>
        {secHeader}
        <StateCard
          title={t("siteTraffic.disconnectedTitle")}
          body={
            accountConnected
              ? t("siteTraffic.disconnectedBody")
              : t("siteTraffic.disconnectedNoAccountBody")
          }
          action={
            accountConnected ? (
              <ConnectAction
                label={t("siteTraffic.connectCta")}
                href={`/dashboard/projects/${projectId}/settings#data-sources`}
              />
            ) : (
              <ConnectAction
                label={t("siteTraffic.connectAccountCta")}
                href="/dashboard/connections"
              />
            )
          }
        />
      </section>
    );
  }

  if (traffic && traffic.status === "revoked") {
    return (
      <section aria-label={t("siteTraffic.title")}>
        {secHeader}
        <StateCard
          title={t("siteTraffic.revokedTitle")}
          body={t("siteTraffic.revokedBody")}
          action={
            // Reconnect re-auths the workspace OAuth grant, which lives on the
            // connections page - a different fix from a missing property binding.
            <ConnectAction label={t("siteTraffic.reconnectCta")} href="/dashboard/connections" />
          }
        />
      </section>
    );
  }

  // SIGV2-1202: the authorization is valid and Google refused the request
  // anyway. Sending this state to the reconnect card is what produced the
  // loop: the customer reconnected, nothing changed, the same card came back.
  // Each reason gets the action that can actually fix it.
  if (traffic && traffic.status === "permission_denied") {
    const reason = "reason" in traffic ? traffic.reason : undefined;
    if (reason === "insufficient_scope") {
      // The grant is missing the Analytics scope, so re-running the OAuth
      // flow is the fix - the one case where reconnecting is the right answer.
      return (
        <section aria-label={t("siteTraffic.title")}>
          {secHeader}
          <StateCard
            title={t("siteTraffic.scopeDeniedTitle")}
            body={t("siteTraffic.scopeDeniedBody")}
            action={
              <ConnectAction label={t("siteTraffic.reconnectCta")} href="/dashboard/connections" />
            }
          />
        </section>
      );
    }
    // A confirmed property denial, and the unclassified denial, both need a
    // different property or a different account - never another reconnect of
    // the same account. The property choice leads; changing account is the
    // secondary route.
    const confirmed = reason === "property_denied";
    // Changing the Google account is only reachable when the workspace holds
    // the grant. A binding authorized by a client magic link has no workspace
    // grant, so that route would lead nowhere; false is the only value that
    // hides it, an unresolved lookup still offers the guidance.
    const canChangeAccount = state.ga4WorkspaceConnected !== false;
    return (
      <section aria-label={t("siteTraffic.title")}>
        {secHeader}
        <StateCard
          title={t(
            confirmed ? "siteTraffic.propertyDeniedTitle" : "siteTraffic.permissionDeniedTitle"
          )}
          body={t(
            confirmed ? "siteTraffic.propertyDeniedBody" : "siteTraffic.permissionDeniedBody"
          )}
          action={
            <div className="flex flex-wrap items-center justify-center gap-2.5">
              <ConnectAction
                label={t("siteTraffic.choosePropertyCta")}
                href={`/dashboard/projects/${projectId}/settings#data-sources`}
              />
              {canChangeAccount ? (
                <Link
                  href="/dashboard/connections"
                  className="inline-flex h-[38px] items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold leading-[normal] hover:border-(--line-btn-hover) max-md:min-h-11"
                >
                  {t("siteTraffic.changeAccountCta")}
                </Link>
              ) : null}
            </div>
          }
        />
      </section>
    );
  }

  if (traffic && traffic.status === "provider_error") {
    return (
      <section aria-label={t("siteTraffic.title")}>
        {secHeader}
        <StateCard
          title={t("siteTraffic.providerErrorTitle")}
          body={t("siteTraffic.providerErrorBody")}
          action={
            <button
              type="button"
              onClick={() => void refetch()}
              className="inline-flex h-[38px] items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold hover:border-(--line-btn-hover)"
            >
              {t("common.tryAgain")}
            </button>
          }
        />
      </section>
    );
  }

  if (!payload) {
    return null;
  }

  const { overview, key_events: keyEvents } = payload;
  const noData = payload.availability === "no_data";
  const sessionsSeries = payload.series.map((p) => p.sessions);
  const keyEventsSeries = payload.series.map((p) => p.key_events);

  // SIGV2-1204: the approved design marks all five KPI cards with
  // `data-xsell` (mockup/Signal Overview.html:88-112), so the help panel
  // belongs to the card itself. It used to mount only when channel_mix
  // happened to carry at least one non-null share_change, which left
  // Sessions/Users/Engagement/Conversions bare on any period without a
  // comparison and left Audience and the unavailable key-event states bare
  // always. Every rendered card now gets a panel.
  //
  // Honest by contract: each card's panel rows are that metric's own measured
  // factors from payload.breakdowns, never shared text (the pre-1260 bug).
  // The two question lines are the approved copy verbatim
  // (mockup/app.js:466-479); which of the two a card uses follows its own
  // measured direction, because the mockup pins "What caused the drop?" onto
  // sample deltas that are all positive. The mockup's explanation line and
  // breakdown rows are the only parts it leaves as self-labelled "Dummy text"
  // with invented factors (Marketing spend, Page speed, Seasonality) that GA4
  // never reports, so those stay as the measured breakdown plus a line
  // stating what is on screen - never an invented attribution.
  const changeText = (change: SiteTrafficChange): string | null => {
    if (change.value === null) {
      return null;
    }
    const sign = change.value >= 0 ? "+" : "";
    return change.kind === "percentage_points"
      ? `${sign}${change.value.toFixed(1)} ${t("siteTraffic.pp")}`
      : `${sign}${(change.value * 100).toFixed(2)}%`;
  };
  // The current period on its own, for a row whose change cannot be computed.
  const valueText = (row: SiteTrafficBreakdownRow): string | null => {
    if (typeof row.value !== "number" || Number.isNaN(row.value)) {
      return null;
    }
    switch (row.value_kind) {
      case "percent":
        return `${row.value.toFixed(1)}%`;
      case "seconds":
        return `${Math.round(row.value)}s`;
      default:
        return compact(row.value);
    }
  };
  // A row shows its change when there is one, and its measured value when
  // there is not. Showing only changes meant a property with no previous
  // period - a new GA4 account, or a window predating the property - dropped
  // every row on every card, and all five panels collapsed onto the same
  // "no breakdown" sentence. That is the identical-tooltip report: the rows
  // were per-metric all along, they were just all being discarded.
  const breakdownRows = (rows: SiteTrafficBreakdownRow[]): SignalXSellRow[] =>
    rows
      .map((r) => {
        const label = r.label ?? t(`siteTraffic.breakdownMetrics.${r.metric}`);
        const change = changeText(r.change);
        if (change !== null) {
          return { label, value: change, negative: r.change.value! < 0 };
        }
        const measured = valueText(r);
        return measured === null ? null : { label, value: measured, negative: false };
      })
      .filter((r) => r !== null);
  const xsellFor = (metric: keyof typeof METRIC_ACCENTS, change?: SiteTrafficChange) => {
    // Optional-chained deliberately. A payload from before this field
    // existed - a cached report, an older backend, the visual-suite stub -
    // has no `breakdowns` at all, and indexing it threw, which took down the
    // whole Traffic and Conversions section rather than one hover panel.
    // No breakdown is a panel without rows, not a missing section.
    const rows = breakdownRows(payload.breakdowns?.[metric] ?? []);
    return {
      question: t(
        change?.value !== null && change?.value !== undefined && change.value < 0
          ? "siteTraffic.xsellDropped"
          : "siteTraffic.xsellMoved"
      ),
      body: rows.length ? t(`siteTraffic.xsellBody_${metric}`) : t("siteTraffic.xsellNoBreakdown"),
      rows,
    };
  };
  // A card with no measured value still renders, so it still carries the
  // approved panel - but there is no change to attribute. The panel states
  // why the number is absent, reusing the state's own existing wording, and
  // carries no breakdown rows.
  // The server's own reason for the audience metric, mapped to copy. Falls
  // back to the previous sentence for a reason we have no string for, so an
  // unrecognised value never leaks a raw key onto the card.
  const audienceReason = (() => {
    const key = overview.audience?.reason;
    const known = ["not_defined", "unavailable"];
    return t(`siteTraffic.audienceReasons.${key && known.includes(key) ? key : "fallback"}`);
  })();
  const xsellUnmeasured = (reason: string) => ({
    question: t("siteTraffic.xsellWhyNotMeasured"),
    body: reason,
    rows: [] as SignalXSellRow[],
  });

  const keyEventsCard = (() => {
    switch (keyEvents.state) {
      case "not_configured":
        return (
          <KpiCard
            metric="conversions"
            label={t("siteTraffic.metricConversions")}
            value={null}
            icon={<MousePointerClick size={19} strokeWidth={1.9} aria-hidden="true" />}
            unavailable={t("siteTraffic.keyEventsNotConfigured")}
            xsell={xsellUnmeasured(t("siteTraffic.keyEventsNotConfigured"))}
          />
        );
      case "unknown":
        return (
          <KpiCard
            metric="conversions"
            label={t("siteTraffic.metricConversions")}
            value={null}
            icon={<MousePointerClick size={19} strokeWidth={1.9} aria-hidden="true" />}
            unavailable={t("siteTraffic.keyEventsUnknown")}
            xsell={xsellUnmeasured(t("siteTraffic.keyEventsUnknown"))}
          />
        );
      case "observed_zero":
      case "active":
      default:
        return (
          <KpiCard
            metric="conversions"
            label={t("siteTraffic.metricConversions")}
            value={compact(keyEvents.total)}
            change={keyEvents.change}
            spark={keyEventsSeries.length >= 2 ? keyEventsSeries : undefined}
            icon={<MousePointerClick size={19} strokeWidth={1.9} aria-hidden="true" />}
            xsell={xsellFor("conversions", keyEvents.change)}
          />
        );
    }
  })();

  return (
    <section aria-label={t("siteTraffic.title")} ref={entranceRef}>
      {secHeader}
      {noData ? (
        <StateCard title={t("siteTraffic.noDataTitle")} body={t("siteTraffic.noDataBody")} />
      ) : (
        <>
          {payload.availability === "partial" && qualityFlags.length > 0 ? (
            <p className="mb-3 flex items-center gap-2 rounded-[10px] border border-(--warn) bg-(--warn-s) px-4 py-2.5 text-[12.5px] font-medium text-(--warn)">
              {t("siteTraffic.partialNotice", { flags: qualityFlags.join(", ") })}
            </p>
          ) : null}
          {/* Approved `.kpis` row: exactly five cards in the mock's order.
              Only sessions, users and key_events carry contract change values,
              so Engagement renders without a delta and Audience keeps the
              contract's unmeasured state. The mock draws a spark on every
              card; the contract's series has no engagement buckets, so no
              spark is drawn rather than inventing one. Every card carries the
              approved `data-xsell` help panel (SIGV2-1204). */}
          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-5">
            <KpiCard
              metric="sessions"
              label={t("siteTraffic.metricSessions")}
              value={compact(overview.sessions)}
              change={overview.changes.sessions}
              spark={sessionsSeries}
              icon={<Activity size={19} strokeWidth={1.9} aria-hidden="true" />}
              xsell={xsellFor("sessions", overview.changes.sessions)}
            />
            <KpiCard
              metric="users"
              label={t("siteTraffic.metricUsers")}
              value={compact(overview.total_users)}
              change={overview.changes.total_users}
              icon={<Users size={19} strokeWidth={1.9} aria-hidden="true" />}
              xsell={xsellFor("users", overview.changes.total_users)}
            />
            <KpiCard
              metric="engagement"
              label={t("siteTraffic.metricEngagement")}
              value={percent(overview.engagement_rate)}
              icon={<MessageCircle size={19} strokeWidth={1.9} aria-hidden="true" />}
              xsell={xsellFor("engagement")}
            />
            {keyEventsCard}
            {/* Contract 2.4: the audience metric has no agreed definition.
                The approved card shape is kept; the value slot carries the
                unmeasured state and the reason sits under it, never a
                number.

                SIGV2-1281: the reason is the server's, not a sentence of our
                own. The payload has carried `overview.audience.reason` all
                along and the card ignored it, printing "not available yet"
                over a backend that was saying `not_defined`. Those are
                different claims: one promises a measurement that is coming,
                the other says there is nothing agreed to measure. An
                unrecognised reason falls back to the old wording rather than
                showing a raw key. */}
            <KpiCard
              metric="audience"
              label={t("siteTraffic.metricAudience")}
              value={null}
              unavailable={t("siteTraffic.notMeasured")}
              reason={audienceReason}
              icon={<GaugeIcon size={19} strokeWidth={1.9} aria-hidden="true" />}
              xsell={xsellUnmeasured(audienceReason)}
            />
          </div>

          {/* Approved `.wrap` gap between the KPI row and this block is 22px
              (signal.css:28), not 16 (SIGV2-1125). */}
          <div className="mt-[22px]">
            {/* Approved `.sec` for this block: a 17px display heading, the
                short 1x16 `.ln` rule, the Google Analytics source line, then
                the grain control pushed right by a spacer (signal.css:29-31,
                145). This used to be a 14px `h3` with a full-width rule and
                the source line on the right, which is both a different
                hierarchy and 14px shorter than the approved row. */}
            <div className="mb-3.5 flex flex-wrap items-center gap-3">
              <h3 className="m-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em]">
                {t("siteTraffic.sourcesTitle")}
              </h3>
              <span className="h-4 w-px flex-none bg-(--line-2)" aria-hidden="true" />
              <span className="flex items-center gap-1 text-[12.5px] text-(--t-3)">
                <span className="inline-block h-[13px] w-[13px] rounded-[3px] bg-[conic-gradient(#F9AB00_0_25%,#E37400_0_50%,#34A853_0_75%,#4285F4_0)]" />
                {t("siteTraffic.gaChannelSource")}
              </span>
              <span className="flex-1 max-md:hidden" />
              {/* The approved Days/Weeks/Months toggle is a grain choice the
                  contract does not offer: granularity is fixed by window, so
                  there is nothing to switch between. The period control in the
                  page header drives the window and the resulting grain is
                  reported read-only (recorded deviation). It carries the
                  approved `.time-seg` box (signal.css:570-571) so the row has
                  the approved height, but it stays one static element rather
                  than a group of buttons: offering choices the contract cannot
                  honour would be worse than the recorded deviation. */}
              <span
                data-traffic-grain
                className="inline-flex flex-none rounded-[9px] border border-(--line) bg-(--panel) p-[3px]"
              >
                <span className="rounded-[6px] px-2.5 py-[5px] text-[12px] font-semibold leading-[normal] text-(--t-2)">
                  {t(`siteTraffic.grain.${payload.bucket_granularity}`, {
                    defaultValue: payload.bucket_granularity,
                  })}
                </span>
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[622fr_488fr]">
              <TrafficChart payload={payload} />
              <div className="flex flex-col rounded-(--r) border border-(--line) bg-(--panel) px-6 py-[22px]">
                <h4 className="m-0 font-(family-name:--disp) text-[14px] font-bold tracking-[-0.01em]">
                  {t("siteTraffic.channelMix")}
                </h4>
                <div className="mt-[18px]">
                  <ChannelDonut payload={payload} />
                </div>
              </div>
            </div>
            {/* Contract 3/7's window, timezone and freshness are stated on
                the GA4 badge in this block's header, not as a paragraph here:
                see `provenance` above. */}
          </div>
        </>
      )}
    </section>
  );
}
